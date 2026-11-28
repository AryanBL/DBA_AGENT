# DBA Agent

An LLM-powered, command-line assistant that develops relational database designs from natural-language requirements through a **six-stage, persisted and versioned workflow**. This is an educational implementation aligned to the DBA Agent Database Laboratory specification; it is not a production database migration service.

## What is implemented

1. **Intake:** Ask an OpenAI-compatible model to structure the user's description (actors, entities, processes, requirements, ambiguities).
2. **Interview:** Ask questions spanning seven required categories, record answers, ask at least one follow-up round, and let the model assess readiness with deterministic validation guards.
3. **DBMS selection:** Choose from PostgreSQL, MySQL/MariaDB, SQLite and SQL Server, including a comparison table and rejection reasons.
4. **Documentation:** Validate one structured design model, then deterministically render requirements, DBMS decision, Mermaid ER diagrams, logical schema, normalization analysis and assumptions.
5. **Revision:** Convert natural-language changes to an updated full model, regenerate the affected documents, preserve prior version folders, record a change log and invalidate previous approval.
6. **SQL.** Require explicit approval, generate DBMS-specific `schema.sql` and `seed.sql`, and test the scripts together in an isolated database before saving them. A separate user command applies the saved files to a running server container or a selected SQLite file.

**Limitations:** Kilo Gateway connectivity and the opening structured workflow have been tested against the live `kilo-auto/free` endpoint, but the complete included test scenario has not been run end to end against a hosted model. Server execution requires an existing running container and a locally available image. Structural checks cannot prove 3NF, completeness, performance, or that generated SQL faithfully implements every rule. The final scenario run, architecture report and critique report remain separate submission tasks.

## Requirements

- Python 3.10+.
- Network access to the configured OpenAI-compatible gateway and credentials for its selected model.
- The transport remains compatible with other **OpenAI-compatible `/chat/completions` endpoints**; no LangChain dependency.
- SQLite is included with Python. Generating SQL for a server DBMS requires Docker and a local image for that DBMS. The offline tests run without Docker.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e .
python -m unittest discover -v
```

## Provider configuration

The defaults use the configured gateway's DeepSeek V4.1 Flash model ID. Override the endpoint and exact model ID with environment variables. `.env.example` is a reference and is **not auto-loaded**.

```bash
export DBA_AGENT_BASE_URL="https://api.gapgpt.app/v1"
export DBA_AGENT_MODEL="gapgpt-deepseek-v4.1-flash"
# Set DBA_AGENT_API_KEY privately in your shell or secret manager.
# optional:
export DBA_AGENT_OUTPUT_DIR="output"
export DBA_AGENT_STATE_DIR=".dba_agent/sessions"
```

On PowerShell:

```powershell
$env:DBA_AGENT_BASE_URL="https://api.gapgpt.app/v1"
$env:DBA_AGENT_MODEL="gapgpt-deepseek-v4.1-flash"
# Set DBA_AGENT_API_KEY privately in your environment.
```

`DBA_AGENT_BASE_URL`, `DBA_AGENT_MODEL`, and `DBA_AGENT_API_KEY` configure the provider without source changes. The gateway must support `/chat/completions`. `KILO_API_KEY` remains a legacy fallback when `DBA_AGENT_API_KEY` is unset. Keys are sent in the Authorization header, excluded from configuration representations, and redacted from new call and validation logs and errors. Inputs and outputs still contain workflow data. Existing historical logs are left intact.

Provider model names are gateway-specific. The DeepSeek ID above comes from the project's existing configuration and has not been verified with a live paid request. Set both URL and model to switch back to another gateway.

## Token efficiency and usage

Each `output/llm-calls.jsonl` entry includes its session ID, provider `usage`, normalized `accounting`, `usage_source`, and error category. Provider prompt/completion counts take precedence individually. Missing counts use a UTF-8 byte length divided by four approximation, rounded up. Estimates include request serialization and cannot reproduce model-specific tokenization, hidden reasoning, billing, or charges for failed network attempts. Cache hits count as calls with zero new provider tokens. Client totals are available as `LLMClient.totals` and `session_totals`; cumulative session totals survive restarts in session `metadata.usage`. Old sessions begin accounting from their next call.

Interview history remains complete in session state. A deterministic summary interns identical answer lines once and represents recent answers using fact and question indexes. It includes established facts, prior coverage judgments, unresolved topics, contradictions, original intake, and previously asked questions. Coverage is reassessed by the model. No answers are truncated. The latest summary is saved in `metadata.interview_summary`.

After an answered round, one model call assesses coverage and returns the next 1–3 targeted follow-up questions. Full requirements are requested only when the model judges the interview ready and at least two rounds have been answered. This avoids sending the full interview context twice between rounds and repeatedly generating requirements that cannot yet be accepted. Assessment and questions are validated together before saving; `/continue` can retry failures using the saved answers. Older saved assessments still support generating questions separately. Restart a running app after updating code or `.env` settings.

Completed requirements replace intake in later stages. Design and revision calls send only the selected DBMS instead of repeating its comparison report. Revisions retain the full model because arbitrary changes must propagate consistently across the entire design. An omitted DBMS choice in a revision response preserves the local complete choice. SQL generation sends table definitions, business rules, assumptions, ambiguities, and transaction/business requirements, omitting normalization and functional-dependency prose.

During SQL generation, the selected engine runs the schema and seed in a fresh database with constraints enabled. SQLite also checks stored values against common declared types. On failure the model receives the database error, the affected statements, and any related definitions. The first repair call gives the full patch instructions. Later calls use a shorter prompt. The program applies only patches to the listed statement IDs and tests the complete pair again. `DBA_AGENT_MAX_SQL_ATTEMPTS` bounds generation and repair attempts. `DBA_AGENT_LLM_ATTEMPTS` bounds retries for network, JSON, and response validation errors.

Server validation uses a disposable Docker container with temporary credentials. Validation and automatic execution both run `docker image ls` to find a compatible local image. They accept versioned tags and prefer MySQL to MariaDB when both are installed. Set `DBA_AGENT_SQL_VALIDATION_IMAGE` to select a specific already-local image for both steps. SQL Server requires `ACCEPT_EULA=Y` in the app's environment. SQLite validation runs in memory.

The cache lives only in the current `LLMClient` process. Keys hash actual serialized inputs, prompt contents, stage, model, base URL and credential identity. Service calls additionally hash full requirements, DBMS choice, authoritative design and version without transmitting that context. Changed inputs cannot hit the old entry. Cached JSON is revalidated and copied before returning. Invalid stage responses are excluded, and failed SQL validation clears the cache. Set `DBA_AGENT_CACHE_ENABLED=0` to disable it. Temperature zero supports repeatable requests but does not guarantee model determinism.

On the existing library call data, compact payload bytes fell 34.7% for an assessment, 12.0% for a revision, and 31.0% for SQL generation inputs reconstructed from the saved model. Approximate input counts fell from 7,404 to 4,838, 9,495 to 8,354, and 7,971 to 5,504 respectively. These measurements compare payloads only, excluding system prompts and responses, and are not provider billing measurements.

## Running the CLI

Open the interactive workspace from the project directory:

```bash
source venv/bin/activate
dba-agent
```

Use the activation path for your environment (`venv` or `.venv`). The full-screen workspace has a session sidebar, conversation history, generated-file previews, and a multiline composer. Type a system description to start, or select a saved session in the sidebar. Paste the opening description from [scenario.md](scenario.md) for the library scenario. Enter sends a message, Shift+Enter inserts a newline, Ctrl+N starts a session, Ctrl+B toggles the sidebar, and Ctrl+Q exits. Completed interview rounds and workflow checkpoints are saved automatically.

Answer interview questions in the composer. When a design is ready, select a file to preview it, type a revision request, or use `/approve`. After approval, use `/sql` to generate both files. Set `DBA_AGENT_SQL_USER` and `DBA_AGENT_SQL_PASSWORD` in `.env` for server databases, then restart the app. Run `/execute-sql` to start a fresh container, create a database and login, and apply both files. The app displays the database and container names. Use `/sql-commands` after a successful container run to show the commands for listing tables and previewing rows again. For SQLite, `/execute-sql` creates a database file beside the SQL files. Use `/execute-sql CONTAINER DATABASE USER` or `/execute-sql DATABASE_FILE` to select an existing server target or a specific SQLite path. `/verify-sqlite` runs an in-memory check. `/continue` resumes an interrupted model stage. `/help` lists all commands.

Use `dba-agent interactive` to open the workspace explicitly. The individual commands below also work for scripts and direct session access.

To delete one saved session, use its UUID from the resume list:

```bash
dba-agent delete SESSION_UUID
```

In the workspace, select a session and type `/delete`, then confirm the dialog. This removes the persisted session record. Generated files under `output/SESSION_UUID/` are retained so design artifacts remain available.

```bash
# 1. Start a new session (the tool prints its UUID and first questions)
python -m dba_agent.cli new "A library tracks members, books, copies, and loans"

# 2. Reply to the questions using the session UUID returned above
python -m dba_agent.cli answer SESSION_UUID

# 3. Answer at least one follow-up round; repeat until DESIGN_READY
python -m dba_agent.cli answer SESSION_UUID

# 4. Read the six generated Markdown documents under output/SESSION_UUID/v1/
python -m dba_agent.cli status SESSION_UUID

# 5. Optional: change the design in natural language
python -m dba_agent.cli revise SESSION_UUID "Each loan can have multiple renewals"

# 6. Approve the CURRENT version explicitly
python -m dba_agent.cli approve SESSION_UUID

# 7. Generate schema.sql and seed.sql
python -m dba_agent.cli sql SESSION_UUID

# 8. Create a database from the generated files using the shared credentials in .env
python -m dba_agent.cli execute-sql SESSION_UUID

# Or load an existing server database using its login
python -m dba_agent.cli execute-sql SESSION_UUID --container CONTAINER --database DATABASE --user USER

# Or, for SQLite, write to a database file selected by the user
python -m dba_agent.cli execute-sql SESSION_UUID --database path/to/database.sqlite

# Optional SQLite in-memory check
python -m dba_agent.cli verify-sqlite SESSION_UUID
```

Execution runs `schema.sql` first and `seed.sql` after the schema succeeds. Automatic server execution uses an already-local image and creates a container with no published ports. A successful run leaves the container running for access through `docker exec`. SQLite uses Python's built-in driver. If you supply an existing target, use an empty database you intend to modify.

`python -m dba_agent.cli continue SESSION_UUID` resumes an interrupted LLM stage. `answer --json answers.json` accepts an object whose keys **exactly** match the displayed question texts.

## Example generated folder layout

```text
.dba_agent/sessions/<uuid>.json         # durable session state
output/
  llm-calls.jsonl                       # every LLM attempt and response/error
  sql-validation.jsonl                  # SQL validation errors, if any
  <uuid>/
    changelog.md
    v1/
      requirements.md
      dbms-choice.md
      conceptual-model.md
      logical-schema.md
      normalization.md
      assumptions.md
      schema.sql                       # only after approval and SQL command
      seed.sql
    v2/                                 # appears following a revision
      ... six revised Markdown files
      schema.sql / seed.sql             # regenerated only after v2 approval
```

## Design and extension points

- `dba_agent/session.py`: state transitions, version snapshots, approval and atomic persistence.
- `dba_agent/interview.py`: seven mandatory categories and Markdown requirements renderer.
- `dba_agent/model.py`: structured DBMS/design validation.
- `dba_agent/config.py`: environment-based settings.
- `dba_agent/llm.py`: provider adapter, prompt file loading, JSON response parsing, per-attempt logs.
- `dba_agent/service.py`: orchestration, checkpoint/retry, revision and SQL pipeline.
- `dba_agent/render.py`: deterministic file output and Mermaid diagrams.
- `dba_agent/sql.py`, `dba_agent/sql_validation.py`, and `dba_agent/sql_statements.py` handle SQLite execution, conflict detection, and statement-level repairs.
- `dba_agent/docker_sql.py`: local-image checks and container execution with `psql`, `mysql`/`mariadb`, or `sqlcmd`.
- `dba_agent/docker_validation.py` runs native validation in disposable database containers.
- `dba_agent/cli.py`: command-line interface.
- `dba_agent/prompts/`: human-readable prompts for each model task.
- `tests/`: deterministic offline tests, including executable SQLite SQL.
- `docs/implementation-guide.md`: detailed architecture and explanation.

To support another API protocol, create a new transport adapter implementing the interface of `LLMClient` rather than altering the stage logic. For production deployment, add database-backed concurrency controls, credential isolation, stronger model/schema validation, and real-DBMS execution for each dialect.

## Tests and sample run

[`scenario.md`](scenario.md) contains a copy-ready community-library scenario, canonical answers for every mandatory interview category, common follow-up answers, run commands, and an acceptance checklist for a manual live test.

```bash
python -m unittest discover -v
```

The test suite uses an injected scripted model (not a real LLM) and validates actual SQLite DDL/DML execution inside an in-memory database. It also checks reloading state, guard conditions, follow-up requirement, revision invalidation, failed-model rollback, and repair-loop behavior. See `tests/test_pipeline.py` for the complete runnable offline example.

## Assignment tracking

The implementation covers the six required workflow stages at a functional prototype level, including persistence, external prompts, provider configuration and local logs. **Still needed before final submission** are an official end-to-end scenario run, the max-three-page architecture report, a genuine critique of at least three design flaws and remediations (or an account of checks performed), and live executable verification against the actual chosen DBMS.
