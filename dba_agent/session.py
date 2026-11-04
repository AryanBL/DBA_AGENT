"""Versioned, persistent domain state. No network, prompting, or UI dependencies."""
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


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateError(ValueError):
    """Invalid transition or persisted state."""


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


SUPPORTED_DBMS = ("PostgreSQL", "MySQL/MariaDB", "SQLite", "SQL Server")


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
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    intake_text: str = ""
    intake_summary: dict[str, Any] = field(default_factory=dict)
    interview_rounds: list[dict[str, Any]] = field(default_factory=list)
    interview_assessment: dict[str, Any] = field(default_factory=dict)
    pending_questions: list[str] = field(default_factory=list)
    requirements: dict[str, Any] = field(default_factory=dict)
    dbms_choice: dict[str, Any] = field(default_factory=dict)
    versions: list[DesignVersion] = field(default_factory=lambda: [DesignVersion(1)])
    active_version: int = 1
    approval_version: int | None = None
    revision_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = now()

    @property
    def design(self) -> DesignVersion:
        for version in self.versions:
            if version.number == self.active_version:
                return version
        raise StateError(f"active design version {self.active_version} is missing")

    def complete_intake(self, intake_text: str, intake_summary: dict[str, Any]) -> None:
        if self.state != Stage.NEW:
            raise StateError("intake requires a new session")
        if not isinstance(intake_text, str) or not intake_text.strip():
            raise StateError("intake text must be a nonempty string")
        required = {"actors", "entities", "processes", "requirements", "ambiguities"}
        if not isinstance(intake_summary, dict) or not required.issubset(intake_summary):
            raise StateError(f"intake summary requires {sorted(required)}")
        for name in required:
            if not isinstance(intake_summary[name], list):
                raise StateError(f"intake summary {name} must be a list")
        self.intake_text, self.intake_summary = intake_text, intake_summary
        self.state = Stage.INTAKE_COMPLETE
        self.touch()

    def start_interview(self) -> None:
        if self.state not in (Stage.INTAKE_COMPLETE, Stage.INTERVIEWING):
            raise StateError("interview requires a completed intake")
        self.state = Stage.INTERVIEWING
        self.touch()

    def set_questions(self, questions: list[str]) -> None:
        if self.state != Stage.INTERVIEWING or self.pending_questions:
            raise StateError("cannot replace pending interview questions")
        if not isinstance(questions, list) or not questions or any(
            not isinstance(q, str) or not q.strip() for q in questions
        ) or len(questions) != len(set(questions)):
            raise StateError("interview questions must be unique nonempty strings")
        self.pending_questions = questions.copy()
        self.touch()

    def add_interview_round(self, questions: list[str], answers: dict[str, str]) -> None:
        if self.state != Stage.INTERVIEWING:
            raise StateError("answers require INTERVIEWING state")
        if not isinstance(questions, list) or not questions or any(not isinstance(q, str) or not q.strip() for q in questions) or not isinstance(answers, dict) or set(answers) != set(questions):
            raise StateError("answers must match all questions in the round")
        if self.pending_questions and questions != self.pending_questions:
            raise StateError("answers do not match pending questions")
        if any(not isinstance(a, str) or not a.strip() for a in answers.values()):
            raise StateError("every interview answer must be a nonempty string")
        self.interview_rounds.append({"questions": list(questions), "answers": dict(answers)})
        self.pending_questions = []
        self.interview_assessment = {}
        self.touch()

    def assess_interview(self, assessment: dict[str, Any]) -> None:
        from .interview import REQUIRED_CATEGORIES
        if self.state != Stage.INTERVIEWING or not self.interview_rounds:
            raise StateError("assessment requires answered interview rounds")
        categories = {key for key, _ in REQUIRED_CATEGORIES}
        if not isinstance(assessment, dict) or not isinstance(assessment.get("ready"), bool):
            raise StateError("assessment must contain a boolean ready field")
        coverage = assessment.get("coverage")
        if not isinstance(coverage, dict) or set(coverage) != categories or any(
            not isinstance(v, bool) for v in coverage.values()
        ):
            raise StateError("assessment must mark all seven categories true/false")
        if not isinstance(assessment.get("critical_contradictions"), list):
            raise StateError("assessment must contain critical_contradictions list")
        if assessment["ready"] and (not all(coverage.values()) or assessment["critical_contradictions"]):
            raise StateError("assessment cannot be ready with gaps or critical contradictions")
        self.interview_assessment = assessment
        self.touch()

    def complete_requirements(self, requirements: dict[str, Any]) -> None:
        if self.state != Stage.INTERVIEWING:
            raise StateError("requirements require INTERVIEWING state")
        if len(self.interview_rounds) < 2:
            raise StateError("at least one follow-up interview round is required")
        assessment = self.interview_assessment
        if not assessment.get("ready") or not all(assessment.get("coverage", {}).values()):
            raise StateError("agent has not determined the interview complete")
        if assessment.get("critical_contradictions"):
            raise StateError("critical contradictions block interview completion")
        from .interview import validate_requirements
        if not isinstance(requirements, dict):
            raise StateError("requirements must be a mapping")
        try:
            validate_requirements(requirements)
        except ValueError as exc:
            raise StateError(str(exc)) from exc
        self.requirements = dict(requirements)
        self.state = Stage.REQUIREMENTS_COMPLETE
        self.touch()

    def requirements_markdown(self) -> str:
        if self.state in (Stage.NEW, Stage.INTAKE_COMPLETE, Stage.INTERVIEWING):
            raise StateError("requirements are not complete")
        from .interview import render_requirements_markdown
        return render_requirements_markdown(self.requirements, self.interview_rounds)

    def select_dbms(self, choice: dict[str, Any]) -> None:
        if self.state != Stage.REQUIREMENTS_COMPLETE:
            raise StateError("DBMS selection requires completed requirements")
        from .model import validate_dbms_choice
        validate_dbms_choice(choice)
        self.dbms_choice = choice
        self.state = Stage.DBMS_SELECTED
        self.touch()

    def set_design(self, model: dict[str, Any]) -> None:
        if self.state not in (Stage.DBMS_SELECTED, Stage.REVISION_PENDING):
            raise StateError("design requires DBMS_SELECTED or REVISION_PENDING")
        from .model import validate_design
        validate_design(model)
        self.design.model = model
        self.state = Stage.DESIGN_READY
        self.touch()

    def revise(self, model: dict[str, Any], reason: str = "", request: str = "", dbms_choice: dict[str, Any] | None = None) -> None:
        if self.state not in (Stage.DESIGN_READY, Stage.APPROVED, Stage.SQL_GENERATED):
            raise StateError("revision requires an existing design")
        from .model import validate_dbms_choice, validate_design
        validate_design(model)
        if dbms_choice is not None:
            validate_dbms_choice(dbms_choice)
        if not request.strip() or not reason.strip():
            raise StateError("revision needs a user request and a reason")
        previous = self.active_version
        number = max(v.number for v in self.versions) + 1
        self.versions.append(DesignVersion(number=number, model=model))
        self.active_version = number
        self.approval_version = None
        if dbms_choice is not None:
            self.dbms_choice = dbms_choice
        self.revision_history.append({"from": previous, "to": number, "request": request, "reason": reason, "timestamp": now(), "affected_files": ["requirements.md", "dbms-choice.md", "conceptual-model.md", "logical-schema.md", "normalization.md", "assumptions.md"], "sql_invalidated": True})
        self.state = Stage.DESIGN_READY
        self.touch()

    def approve(self) -> None:
        if self.state != Stage.DESIGN_READY or not self.design.model:
            raise StateError("only a completed design can be approved")
        self.approval_version = self.active_version
        self.design.approved_at = now()
        self.state = Stage.APPROVED
        self.touch()

    def require_sql_approval(self) -> None:
        if self.state != Stage.APPROVED or self.approval_version != self.active_version:
            raise StateError("SQL generation requires approval of the active design version")

    def mark_sql_generated(self) -> None:
        self.require_sql_approval()
        self.state = Stage.SQL_GENERATED
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = self.state.value
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Session:
        try:
            value = dict(value)
            value["state"] = Stage(value["state"])
            value["versions"] = [DesignVersion(**item) for item in value["versions"]]
            session = cls(**value)
            session.design
            if session.approval_version is not None and session.approval_version != session.active_version:
                raise StateError("approval does not belong to the active design")
            if session.state in (Stage.APPROVED, Stage.SQL_GENERATED) and session.approval_version is None:
                raise StateError("approved session missing approval version")
            return session
        except (KeyError, TypeError, ValueError) as exc:
            raise StateError(f"invalid session document: {exc}") from exc


class SessionStore:
    """Atomic JSON storage under UUID-named session files."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, session_id: str) -> Path:
        try:
            canonical = str(uuid.UUID(session_id))
        except (ValueError, TypeError) as exc:
            raise StateError("session id must be a canonical UUID") from exc
        if canonical != session_id:
            raise StateError("session id must be a canonical UUID")
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
        try:
            with self.path_for(session_id).open(encoding="utf-8") as handle:
                return Session.from_dict(json.load(handle))
        except FileNotFoundError as exc:
            raise StateError(f"session not found: {session_id}") from exc
        except json.JSONDecodeError as exc:
            raise StateError(f"invalid JSON for session {session_id}: {exc}") from exc
