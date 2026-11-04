"""Six-stage orchestration with saved checkpoints, versioning and artifact propagation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .interview import REQUIRED_CATEGORIES, validate_requirements
from .llm import LLMClient, append_jsonl
from .model import validate_dbms_choice, validate_design
from .render import render_session, write_file
from .session import Session, SessionStore, Stage, StateError
from .sql import execute_sqlite, validate_sql_artifacts


class AgentService:
    def __init__(self, config: Config, llm: LLMClient | None = None):
        self.config = config
        self.llm = llm or LLMClient(config)
        self.store = SessionStore(config.state_dir)

    def _save(self, session: Session) -> Session:
        self.store.save(session)
        return session

    def get(self, session_id: str) -> Session:
        return self.store.load(session_id)

    def create(self, description: str) -> Session:
        session = Session()
        summary = self.llm.ask("intake", "intake", {"description": description})
        session.complete_intake(description, summary)
        self._save(session)
        session.start_interview()
        self._save(session)
        return self.advance(session.session_id)

    def advance(self, session_id: str) -> Session:
        """Resume a partially completed step after a network failure or process restart."""
        session = self.get(session_id)
        if session.state == Stage.INTERVIEWING:
            if session.pending_questions:
                return session
            if session.interview_rounds and not session.interview_assessment:
                response = self.llm.ask("interview", "assess", {
                    "intake": session.intake_summary, "rounds": session.interview_rounds,
                    "mandatory_categories": [k for k, _ in REQUIRED_CATEGORIES],
                })
                session.assess_interview(response)
                self._save(session)
            if session.interview_assessment and session.interview_assessment["ready"] and len(session.interview_rounds) >= 2:
                if not all(session.interview_assessment["coverage"].values()) or session.interview_assessment["critical_contradictions"]:
                    raise StateError("model assessment is internally contradictory")
                requirements = session.interview_assessment.get("requirements")
                session.complete_requirements(requirements)
                self._save(session)
            else:
                if len(session.interview_rounds) >= self.config.max_interview_rounds:
                    raise StateError("interview is incomplete after the configured maximum rounds; review the recorded answers")
                questions = self.llm.ask("interview", "questions", {
                    "intake": session.intake_summary,
                    "rounds": session.interview_rounds,
                    "assessment": session.interview_assessment,
                    "follow_up_required": bool(session.interview_rounds),
                    "mandatory_categories": [k for k, _ in REQUIRED_CATEGORIES],
                })
                session.set_questions(questions.get("questions"))
                return self._save(session)
        if session.state == Stage.REQUIREMENTS_COMPLETE:
            choice = self.llm.ask("dbms_selection", "dbms", {"requirements": session.requirements})
            session.select_dbms(choice)
            self._save(session)
        if session.state == Stage.DBMS_SELECTED:
            model_response = self.llm.ask("design", "design", {
                "intake": session.intake_summary,
                "requirements": session.requirements,
                "dbms_choice": session.dbms_choice,
            })
            model = model_response.get("design")
            session.set_design(model)
            self._save(session)
            render_session(session, self.config.output_dir)
            self._save(session)
        if session.state == Stage.DESIGN_READY and not session.design.artifacts:
            render_session(session, self.config.output_dir)
            self._save(session)
        return session

    def answer(self, session_id: str, answers: dict[str, str]) -> Session:
        session = self.get(session_id)
        if session.state != Stage.INTERVIEWING or not session.pending_questions:
            raise StateError("no unanswered interview questions")
        session.add_interview_round(session.pending_questions, answers)
        self._save(session)
        return self.advance(session.session_id)

    def revise(self, session_id: str, request: str) -> Session:
        session = self.get(session_id)
        if not request.strip():
            raise StateError("revision request cannot be empty")
        output = self.llm.ask("revision", "revision", {
            "request": request, "intake": session.intake_summary,
            "requirements": session.requirements,
            "dbms_choice": session.dbms_choice,
            "current_design": session.design.model,
        })
        new_requirements = output.get("requirements")
        validate_requirements(new_requirements)
        new_choice = output.get("dbms_choice")
        validate_dbms_choice(new_choice)
        new_model = output.get("design")
        validate_design(new_model)
        session.revise(new_model, reason=output.get("reason", ""), request=request, dbms_choice=new_choice)
        session.requirements = new_requirements
        self._save(session)
        render_session(session, self.config.output_dir)
        return self._save(session)

    def approve(self, session_id: str) -> Session:
        session = self.get(session_id)
        session.approve()
        return self._save(session)

    def generate_sql(self, session_id: str, verify_sqlite: bool = False) -> dict[str, Any]:
        session = self.get(session_id)
        session.require_sql_approval()
        tables = [t["name"] for t in session.design.model["tables"]]
        dbms = session.dbms_choice["selected"]
        if verify_sqlite and dbms != "SQLite":
            raise StateError("--verify-sqlite only supports sessions whose selected DBMS is SQLite")
        payload = {"dbms": dbms, "design": session.design.model, "requirements": session.requirements}
        last_error = ""
        for attempt in range(1, self.config.max_sql_attempts + 1):
            stage = "sql" if attempt == 1 else "sql_repair"
            response = self.llm.ask(stage, stage, payload)
            schema, seed = response.get("schema_sql"), response.get("seed_sql")
            try:
                validate_sql_artifacts(schema, seed, tables)
                counts = execute_sqlite(schema, seed, tables, session.design.model) if verify_sqlite else None
                path = self.config.output_dir / session.session_id / f"v{session.active_version}"
                # Only publish both files after checks pass, avoiding partially updated versions.
                write_file(path / "schema.sql", schema)
                write_file(path / "seed.sql", seed)
                session.design.artifacts.update({"schema.sql": str(path / "schema.sql"), "seed.sql": str(path / "seed.sql")})
                session.mark_sql_generated()
                self._save(session)
                return {"schema": str(path / "schema.sql"), "seed": str(path / "seed.sql"), "verified_sqlite": verify_sqlite, "counts": counts, "attempts": attempt}
            except StateError as exc:
                last_error = str(exc)
                append_jsonl(self.config.output_dir / "sql-validation.jsonl", {"session_id": session_id, "version": session.active_version, "attempt": attempt, "dbms": dbms, "error": last_error})
                payload = {"dbms": dbms, "design": session.design.model, "requirements": session.requirements, "previous_schema": schema, "previous_seed": seed, "validation_error": last_error}
        raise StateError(f"SQL failed validation after {self.config.max_sql_attempts} attempt(s): {last_error}")
