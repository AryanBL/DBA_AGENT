# DBA Agent Workflow Contract — Implemented Version

This contract documents the behavior of the revised code, not features that are only planned. The source of truth is the JSON-persisted `Session` and its active `DesignVersion.model`.

## States

`NEW` -> `INTAKE_COMPLETE` -> `INTERVIEWING` -> `REQUIREMENTS_COMPLETE` -> `DBMS_SELECTED` -> `DESIGN_READY` -> `APPROVED` -> `SQL_GENERATED`.

The interview remains in `INTERVIEWING` for additional rounds. A successful revision of a complete design creates a new version and returns directly to `DESIGN_READY`, clearing `approval_version`. The legacy `REVISION_PENDING` enum is retained for compatibility but not used as an externally visible intermediate state by the current revision method.

## Stage contracts

| Stage | Input | Output / guard |
|---|---|---|
| 1. Intake | User free text | Five-list intake summary (`actors`, `entities`, `processes`, `requirements`, `ambiguities`) and saved session. |
| 2. Interview | Summary, previous Q&A | Question/answer rounds, model completeness assessment, seven-category requirements. At least one answered follow-up round; the agent must declare readiness and no critical contradictions. |
| 3. DBMS | Completed requirements | Selection of PostgreSQL, MySQL/MariaDB, SQLite, or SQL Server, comparison of all four and rejection reasons for other three. |
| 4. Design | Requirements, DBMS | One validated structured model and deterministic `requirements.md`, `dbms-choice.md`, `conceptual-model.md`, `logical-schema.md`, `normalization.md`, `assumptions.md`. Mermaid ER diagram included. |
| 5. Revision | Existing model and user request | Validated new requirements/choice/model, new design version, re-rendered six Markdown files, `changelog.md`, invalidated approval. Old SQL never reused for new version. |
| 6. SQL | Current explicitly approved version | `schema.sql` and `seed.sql` after coverage checks and successful execution in an isolated database. Failures can trigger scoped LLM repairs. |
| Execution | Separate user command after both SQL files exist | PostgreSQL via `psql`, MySQL/MariaDB via `mysql` or `mariadb`, and SQL Server via `sqlcmd` in a running container with a locally available image; SQLite into a selected database file. |

## Model and artifact ownership

`Session` stores the original description, interview rounds, consolidated requirements and latest DBMS choice. `DesignVersion.model` stores tables, columns, keys, constraints, indexes, relationships, functional dependencies, normal-form claims, assumptions, ambiguities and business rules. The deterministic renderers produce documentation from this state. SQL is synthesized using an LLM from the approved structured model and checked separately.

All generated Markdown files go into `output/<session-id>/v<version>/`. After approval, SQL for that version is added to that directory. `output/<session-id>/changelog.md` documents versions. `output/llm-calls.jsonl` stores an entry per LLM call attempt, including inputs, outputs or errors. The durable JSON state is stored in `.dba_agent/sessions/<uuid>.json` using atomic replacement.

## Approved-version invariant

`Session.approve()` records the active version. `Session.require_sql_approval()` rejects SQL generation if state is not `APPROVED` or the approval refers to a different version. `Session.revise()` invalidates approval. `Session.mark_sql_generated()` is invoked only after SQL passes its configured checks. These checks do not prove all business rules or normal forms are correct.

## Known boundaries

All prompt steps require a model speaking an OpenAI-compatible chat-completions API. Other protocols require an adapter. Kilo Gateway connectivity and the opening intake and interview workflow have been live-tested. A full hosted-model run of `scenario.md` remains pending. SQL generation validates server SQL in a disposable container built from a local image and validates SQLite SQL with Python's built-in driver in memory. The separate execution command applies validated artifacts to the user-selected database.
