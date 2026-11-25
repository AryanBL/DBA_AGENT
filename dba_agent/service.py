"""Six-stage orchestration with saved checkpoints, versioning and artifact propagation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .context import interview_summary, sql_design, repair_context
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

    def _ask(self, session: Session, stage: str, prompt: str, payload: dict[str, Any], validator=None):
        if "interview_summary" in payload:
            session.metadata["interview_summary"] = payload["interview_summary"]
        before = dict(self.llm.session_totals.get(session.session_id, {}))
        try:
            return self.llm.ask(stage, prompt, payload, session_id=session.session_id, validator=validator,
                cache_context={"requirements": session.requirements, "dbms_choice": session.dbms_choice,
                               "design": session.design.model, "version": session.active_version})
        finally:
            totals = session.metadata.setdefault("usage", {})
            for key, count in self.llm.session_totals.get(session.session_id, {}).items():
                totals[key] = totals.get(key, 0) + count - before.get(key, 0)
            self._save(session)

    def get(self, session_id: str) -> Session:
        return self.store.load(session_id)

    def delete(self, session_id: str) -> None:
        self.store.delete(session_id)

    def create(self, description: str) -> Session:
        session = Session()
        session.intake_text = description
        summary = self._ask(session, "intake", "intake", {"description": description},
                            lambda value: Session().complete_intake(description, value))
        session.complete_intake(description, summary)
        self._save(session)
        return self.advance(session.session_id)

    def _record_interview_assessment(self, session: Session, response: dict[str, Any]) -> None:
        """Validate assessment and its next action together before checkpointing."""
        session.assess_interview(response)
        if response["ready"] and len(session.interview_rounds) >= 2:
            validate_requirements(response.get("requirements"))
        elif len(session.interview_rounds) < self.config.max_interview_rounds:
            session.set_questions(response.get("questions"))

    def advance(self, session_id: str) -> Session:
        """Resume a partially completed step after a network failure or process restart."""
        session = self.get(session_id)
        if session.state == Stage.NEW:
            summary = self._ask(session, "intake", "intake", {"description": session.intake_text},
                                lambda value: Session().complete_intake(session.intake_text, value))
            session.complete_intake(session.intake_text, summary)
            self._save(session)
        if session.state == Stage.INTAKE_COMPLETE:
            session.start_interview()
            self._save(session)
        if session.state == Stage.INTERVIEWING:
            if session.pending_questions:
                return session
            if session.interview_rounds and not session.interview_assessment:
                response = self._ask(session, "interview", "assess", {
                    "interview_summary": interview_summary(session),
                    "mandatory_categories": [k for k, _ in REQUIRED_CATEGORIES],
                    "follow_up_allowed": len(session.interview_rounds) < self.config.max_interview_rounds,
                }, lambda value: self._record_interview_assessment(Session.from_dict(session.to_dict()), value))
                self._record_interview_assessment(session, response)
                self._save(session)
                if session.pending_questions:
                    return session
            if session.interview_assessment and session.interview_assessment["ready"] and len(session.interview_rounds) >= 2:
                if not all(session.interview_assessment["coverage"].values()) or session.interview_assessment["critical_contradictions"]:
                    raise StateError("model assessment is internally contradictory")
                requirements = session.interview_assessment.get("requirements")
                session.complete_requirements(requirements)
                self._save(session)
            else:
                if len(session.interview_rounds) >= self.config.max_interview_rounds:
                    raise StateError("interview is incomplete after the configured maximum rounds; review the recorded answers")
                questions = self._ask(session, "interview", "questions", {
                    "interview_summary": interview_summary(session),
                    "follow_up_required": bool(session.interview_rounds),
                    "mandatory_categories": [k for k, _ in REQUIRED_CATEGORIES],
                }, lambda value: Session.from_dict(session.to_dict()).set_questions(value.get("questions")))
                session.set_questions(questions.get("questions"))
                return self._save(session)
        if session.state == Stage.REQUIREMENTS_COMPLETE:
            choice = self._ask(session, "dbms_selection", "dbms", {"requirements": session.requirements}, validate_dbms_choice)
            session.select_dbms(choice)
            self._save(session)
        if session.state == Stage.DBMS_SELECTED:
            model_response = self._ask(session, "design", "design", {
                "requirements": session.requirements,
                "dbms_choice": {"selected": session.dbms_choice["selected"]},
            }, lambda value: validate_design(value.get("design")))
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
        def validate_revision(value):
            validate_requirements(value.get("requirements"))
            validate_dbms_choice(value.get("dbms_choice", session.dbms_choice))
            validate_design(value.get("design"))
            if not isinstance(value.get("reason"), str) or not value["reason"].strip():
                raise StateError("revision requires a reason")

        output = self._ask(session, "revision", "revision", {
            "request": request,
            "requirements": session.requirements,
            "dbms_choice": {"selected": session.dbms_choice["selected"]},
            "current_design": session.design.model,
        }, validate_revision)
        new_requirements = output.get("requirements")
        validate_requirements(new_requirements)
        new_choice = output.get("dbms_choice", session.dbms_choice)
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
        payload = {"dbms": dbms, "design": sql_design(session.design.model),
                   "requirements": {key: session.requirements[key] for key in ("business_rules", "transactions")}}
        last_error = ""
        for attempt in range(1, self.config.max_sql_attempts + 1):
            stage = "sql" if attempt == 1 else "sql_repair"
            response = self._ask(session, stage, stage, payload)
            if payload.get("mode") == "append_seed" and isinstance(response.get("seed_fragment"), str):
                seed += "\n" + response["seed_fragment"]
            elif payload.get("mode") == "append_schema" and isinstance(response.get("schema_fragment"), str):
                schema += "\n" + response["schema_fragment"]
            else:
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
                last_error = self.llm.redact(str(exc))
                self.llm.cache.clear()  # Never reuse SQL that failed executable validation.
                append_jsonl(self.config.output_dir / "sql-validation.jsonl", self.llm.redact({"session_id": session_id, "version": session.active_version, "attempt": attempt, "dbms": dbms, "error": last_error, "error_kind": "validation"}))
                payload = repair_context(schema, seed, session.design.model, last_error, dbms)
        raise StateError(f"SQL failed validation after {self.config.max_sql_attempts} attempt(s): {last_error}")
