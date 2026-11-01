"""Persistent, versioned workflow state for DBA Agent.

This module deliberately has no LLM or UI dependency.  It is the durable domain
boundary that later workflow stages will use.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class StateError(ValueError):
    """Raised when a state transition or persisted document is invalid."""


class Stage(str, Enum):
    NEW = "NEW"
    INTAKE_COMPLETE = "INTAKE_COMPLETE"
    INTERVIEWING = "INTERVIEWING"
    REQUIREMENTS_COMPLETE = "REQUIREMENTS_COMPLETE"
    DBMS_SELECTED = "DBMS_SELECTED"
    DESIGN_READY = "DESIGN_READY"
    REVISION_PENDING = "REVISION_PENDING"
    APPROVED = "APPROVED"
    SQL_GENERATED = "SQL_GENERATED"


@dataclass
class DesignVersion:
    number: int
    model: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    approved_at: str | None = None


@dataclass
class Session:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: Stage = Stage.NEW
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    intake_text: str = ""
    intake_summary: dict[str, Any] = field(default_factory=dict)
    interview_rounds: list[dict[str, Any]] = field(default_factory=list)
    requirements: dict[str, Any] = field(default_factory=dict)
    dbms_choice: dict[str, Any] = field(default_factory=dict)
    versions: list[DesignVersion] = field(default_factory=lambda: [DesignVersion(1)])
    active_version: int = 1
    approval_version: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    @property
    def design(self) -> DesignVersion:
        for version in self.versions:
            if version.number == self.active_version:
                return version
        raise StateError(f"active design version {self.active_version} is missing")

    def complete_intake(self, intake_text: str, intake_summary: dict[str, Any]) -> None:
        """Accept a structured intake summary and advance to interviewing.

        The summary is the reviewed output of the intake stage.  Keeping this
        transition explicit prevents an interview from starting with an empty
        or incomplete understanding of the user's system.
        """
        if self.state != Stage.NEW:
            raise StateError("intake can only be completed for a new session")
        if not isinstance(intake_text, str) or not intake_text.strip():
            raise StateError("intake text must be a non-empty string")
        if not isinstance(intake_summary, dict):
            raise StateError("intake summary must be an object")
        required = {"actors", "entities", "processes", "requirements", "ambiguities"}
        if not required.issubset(intake_summary):
            raise StateError(f"missing intake fields: {sorted(required - intake_summary.keys())}")
        self.intake_text = intake_text
        self.intake_summary = intake_summary
        self.state = Stage.INTAKE_COMPLETE
        self.touch()

    def start_interview(self) -> None:
        if self.state not in (Stage.INTAKE_COMPLETE, Stage.INTERVIEWING):
            raise StateError("interview requires a completed intake summary")
        self.state = Stage.INTERVIEWING
        self.touch()

    def add_interview_round(self, questions: list[str], answers: dict[str, str]) -> None:
        if self.state != Stage.INTERVIEWING:
            raise StateError("interview answers require INTERVIEWING state")
        if not questions or any(not isinstance(question, str) or not question.strip() for question in questions):
            raise StateError("interview questions must be non-empty strings")
        if not isinstance(answers, dict) or any(
            not isinstance(question, str) or not question.strip() or not isinstance(answer, str) or not answer.strip()
            for question, answer in answers.items()
        ):
            raise StateError("interview answers must be a mapping of non-empty strings")
        self.interview_rounds.append({"questions": questions, "answers": answers})
        self.touch()

    def complete_requirements(self, requirements: dict[str, Any]) -> None:
        if self.state != Stage.INTERVIEWING:
            raise StateError("requirements can only complete an active interview")
        if len(self.interview_rounds) < 2:
            raise StateError("at least one follow-up interview round is required")
        required = {"entities", "relationships", "volume", "workload", "transactions", "security", "business_rules"}
        if not required.issubset(requirements):
            raise StateError(f"missing interview categories: {sorted(required - requirements.keys())}")
        from .interview import validate_requirements

        try:
            validate_requirements(requirements)
        except ValueError as exc:
            raise StateError(str(exc)) from exc
        self.requirements = requirements
        self.state = Stage.REQUIREMENTS_COMPLETE
        self.touch()

    def requirements_markdown(self) -> str:
        """Return the requirements artifact for the completed interview."""
        if self.state not in (Stage.REQUIREMENTS_COMPLETE, Stage.DBMS_SELECTED,
                              Stage.DESIGN_READY, Stage.REVISION_PENDING,
                              Stage.APPROVED, Stage.SQL_GENERATED):
            raise StateError("requirements are not complete")
        from .interview import render_requirements_markdown

        return render_requirements_markdown(self.requirements, self.interview_rounds)

    def revise(self, model: dict[str, Any], artifacts: dict[str, str] | None = None) -> None:
        number = self.versions[-1].number + 1
        self.versions.append(DesignVersion(number, model, artifacts or {}))
        self.active_version = number
        self.approval_version = None
        self.state = Stage.REVISION_PENDING
        self.touch()

    def approve(self) -> None:
        if self.state not in (Stage.DESIGN_READY, Stage.REVISION_PENDING):
            raise StateError("only a ready or revised design can be approved")
        self.approval_version = self.active_version
        self.design.approved_at = datetime.now(timezone.utc).isoformat()
        self.state = Stage.APPROVED
        self.touch()

    def require_sql_approval(self) -> None:
        if self.state != Stage.APPROVED or self.approval_version != self.active_version:
            raise StateError("SQL generation requires approval of the active design version")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Session":
        try:
            value = dict(value)
            value["state"] = Stage(value["state"])
            value["versions"] = [DesignVersion(**item) for item in value["versions"]]
            session = cls(**value)
            session.design  # validate active version
            return session
        except (KeyError, TypeError, ValueError) as exc:
            raise StateError(f"invalid session document: {exc}") from exc


class SessionStore:
    """JSON-backed store with atomic replacement and isolated session files."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id:
            raise StateError("invalid session id")
        return self.root / f"{session_id}.json"

    def save(self, session: Session) -> Path:
        session.touch()
        destination = self.path_for(session.session_id)
        fd, temporary = tempfile.mkstemp(prefix=f".{session.session_id}.", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(session.to_dict(), handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return destination

    def load(self, session_id: str) -> Session:
        path = self.path_for(session_id)
        try:
            with path.open(encoding="utf-8") as handle:
                return Session.from_dict(json.load(handle))
        except FileNotFoundError as exc:
            raise StateError(f"session not found: {session_id}") from exc

