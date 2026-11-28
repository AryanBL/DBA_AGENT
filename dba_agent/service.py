"""Six-stage orchestration with saved checkpoints, versioning and artifact propagation."""
from __future__ import annotations

import os
import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import Config
from .context import interview_summary, sql_design
from .docker_sql import execute_docker_sql, provision_docker_sql
from .docker_validation import docker_seed_validator
from .interview import REQUIRED_CATEGORIES, validate_requirements
from .llm import LLMClient, append_jsonl
from .model import validate_dbms_choice, validate_design
from .render import render_session, write_file
from .session import Session, SessionStore, Stage, StateError
from .sql import execute_sqlite
from .sql_validation import SQLArtifacts, SQLConflict, validate_sqlite_seed


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

    def generate_sql(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        session.require_sql_approval()
        tables = [t["name"] for t in session.design.model["tables"]]
        dbms = session.dbms_choice["selected"]
        payload = {"dbms": dbms, "design": sql_design(session.design.model),
                   "requirements": {key: session.requirements[key] for key in ("business_rules", "transactions")}}

        def require_scripts(value: dict[str, Any]) -> None:
            if any(not isinstance(value.get(key), str) for key in ("schema_sql", "seed_sql")):
                raise StateError("Return schema_sql and seed_sql as SQL strings.")

        with ExitStack() as resources:
            validate_seed = validate_sqlite_seed
            if dbms != "SQLite":
                validator = resources.enter_context(docker_seed_validator(dbms, self.config.sql_validation_image))
                validate_seed = validator.validate
            response = self._ask(session, "sql", "sql", payload, require_scripts)
            artifacts = SQLArtifacts(response["schema_sql"], response["seed_sql"], dbms)
            for attempt in range(1, self.config.max_sql_attempts + 1):
                patch_error = None
                if attempt > 1:
                    prompt = "sql_repair" if attempt == 2 else "sql_repair_followup"
                    patch = self._ask(session, "sql_repair", prompt, payload)
                    try:
                        artifacts.apply(patch, payload["editable"])
                    except StateError as exc:
                        patch_error = self.llm.redact(str(exc))
                if patch_error is not None:
                    last_error = payload["patch_error"] = patch_error
                else:
                    try:
                        artifacts.preflight(tables)
                        validate_seed(artifacts, tables)
                        break
                    except SQLConflict as exc:
                        payload = artifacts.repair_context(exc, session.design.model)
                        last_error = payload["validation_error"] = self.llm.redact(str(exc))
                self.llm.cache.clear()
                append_jsonl(self.config.output_dir / "sql-validation.jsonl", self.llm.redact({
                    "session_id": session_id, "version": session.active_version, "attempt": attempt,
                    "dbms": dbms, "error": last_error, "error_kind": "validation",
                }))
            else:
                raise StateError(f"SQL failed validation after {self.config.max_sql_attempts} attempt(s): {last_error}")

        path = self.config.output_dir / session.session_id / f"v{session.active_version}"
        for file, source in artifacts.sources.items():
            label = f"{file}.sql"
            session.design.artifacts[label] = str(write_file(path / label, source))
        session.mark_sql_generated()
        self._save(session)
        return {"schema": str(path / "schema.sql"), "seed": str(path / "seed.sql"), "attempts": attempt}

    def _generated_files(self, session: Session) -> tuple[Path, Path]:
        if session.state != Stage.SQL_GENERATED:
            raise StateError("Generate both schema.sql and seed.sql with the sql command before execution.")
        folder = self.config.output_dir / session.session_id / f"v{session.active_version}"
        paths = (folder / "schema.sql", folder / "seed.sql")
        for path in paths:
            if session.design.artifacts.get(path.name) != str(path) or not path.is_file() or not path.read_bytes().strip():
                raise StateError(f"The active version is missing {path.name}; generate both SQL files before execution.")
        return paths

    def execute_sql(self, session_id: str, *, container: str = "", database: str = "",
                    username: str = "", password: str = "") -> dict[str, Any]:
        """Execute existing generated files only after the user calls this method."""
        session = self.get(session_id)
        schema, seed = self._generated_files(session)
        dbms = session.dbms_choice["selected"]
        if not database.strip() and not container.strip():
            table = session.design.model["tables"][0]["name"].lower()
            slug = re.sub(r"[^a-z0-9_]+", "_", table).strip("_")[:25] or "database"
            database = f"dba_{slug}_v{session.active_version}_{uuid4().hex[:8]}"
            if dbms == "SQLite":
                database = str(schema.parent / f"{database}.sqlite")
        if dbms == "SQLite":
            if not database.strip():
                raise StateError("A SQLite database file path is required; SQL was not executed.")
            database_path = Path(database).expanduser()
            if database_path.resolve() in (schema.resolve(), seed.resolve()):
                raise StateError("The SQLite database path cannot be a generated SQL file; SQL was not executed.")
            counts = execute_sqlite(schema.read_text(encoding="utf-8"), seed.read_text(encoding="utf-8"),
                                    [table["name"] for table in session.design.model["tables"]],
                                    session.design.model, database=database_path)
            return {"executed": True, "dbms": dbms, "database": str(database_path),
                    "schema": str(schema), "seed": str(seed), "counts": counts}
        if not container.strip():
            result = provision_docker_sql(schema, seed, dbms=dbms, database=database,
                                          username=os.getenv("DBA_AGENT_SQL_USER", "").strip(),
                                          password=os.getenv("DBA_AGENT_SQL_PASSWORD", ""),
                                          image_override=self.config.sql_validation_image)
        else:
            result = execute_docker_sql(schema, seed, dbms=dbms,
                                        container=container, database=database,
                                        username=username or os.getenv("DBA_AGENT_SQL_USER", "").strip(),
                                        password=password or os.getenv("DBA_AGENT_SQL_PASSWORD", ""))
        if result.get("executed") and result.get("inspection_commands"):
            session.metadata["sql_inspection"] = {
                "version": session.active_version,
                "commands": result["inspection_commands"],
            }
            self._save(session)
        return result

    def sql_inspection_commands(self, session_id: str) -> dict[str, str]:
        session = self.get(session_id)
        saved = session.metadata.get("sql_inspection", {})
        if (session.state != Stage.SQL_GENERATED or saved.get("version") != session.active_version
                or not saved.get("commands")):
            raise StateError("No inspection commands for this SQL version. Run `/execute-sql` successfully first.")
        return saved["commands"]

    def verify_sqlite(self, session_id: str) -> dict[str, Any]:
        """Run a separate in-memory verification after both files are generated."""
        session = self.get(session_id)
        if session.dbms_choice["selected"] != "SQLite":
            raise StateError("SQLite verification requires a SQLite design.")
        schema_path, seed_path = self._generated_files(session)
        tables = [table["name"] for table in session.design.model["tables"]]
        counts = execute_sqlite(schema_path.read_text(encoding="utf-8"),
                                seed_path.read_text(encoding="utf-8"), tables, session.design.model)
        return {"schema": str(schema_path), "seed": str(seed_path), "counts": counts, "verified_sqlite": True}
