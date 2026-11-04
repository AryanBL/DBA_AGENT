# DBA Agent

An LLM-powered, command-line assistant that develops relational database designs from natural-language requirements through a **six-stage, persisted and versioned workflow**. This is an educational implementation aligned to the DBA Agent Database Laboratory specification; it is not a production database migration service.

## What is implemented

1. **Intake:** Ask an OpenAI-compatible model to structure the user's description (actors, entities, processes, requirements, ambiguities).
2. **Interview:** Ask questions spanning seven required categories, record answers, ask at least one follow-up round, and let the model assess readiness with deterministic validation guards.
3. **DBMS selection:** Choose from PostgreSQL, MySQL/MariaDB, SQLite and SQL Server, including a comparison table and rejection reasons.
4. **Documentation:** Validate one structured design model, then deterministically render requirements, DBMS decision, Mermaid ER diagrams, logical schema, normalization analysis and assumptions.
5. **Revision:** Convert natural-language changes to an updated full model, regenerate the affected documents, preserve prior version folders, record a change log and invalidate previous approval.
6. **SQL:** Require explicit approval, generate DBMS-specific `schema.sql` and `seed.sql`, run table-coverage checks and support **real SQLite in-memory execution, schema-catalog comparisons and foreign-key validation** (optional). A bounded SQL repair loop passes error feedback to the model.

**Limitations:** This implementation has not been tested with a live hosted LLM in this environment. Only SQLite SQL execution is automated; PostgreSQL, MySQL/MariaDB and SQL Server must be tested using their own servers before claiming executable correctness. Structural checks cannot prove 3NF, completeness, performance, or that generated SQL faithfully implements every rule. No project-specific `scenario.md` was supplied with the source archive. The official scenario run, architecture report and critique report remain separate submission tasks.

## Requirements

- Python 3.10+.
- Network access and a valid API key for an **OpenAI-compatible `/chat/completions` endpoint**; no LangChain dependency.
- SQLite is included with Python for optional executable tests. No external database service is necessary for the mocked tests.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e .
python -m unittest discover -v
```

## Provider configuration

The example values below are placeholders. Set them as environment variables (the `.env.example` file is for reference only; it is **not auto-loaded**):

```bash
export DBA_AGENT_BASE_URL="https://api.openai.com/v1"
export DBA_AGENT_MODEL="YOUR_MODEL_ID"
export DBA_AGENT_API_KEY="YOUR_API_KEY"
# optional:
export DBA_AGENT_OUTPUT_DIR="output"
export DBA_AGENT_STATE_DIR=".dba_agent/sessions"
```

On PowerShell:

```powershell
$env:DBA_AGENT_BASE_URL="https://api.openai.com/v1"
$env:DBA_AGENT_MODEL="YOUR_MODEL_ID"
$env:DBA_AGENT_API_KEY="YOUR_API_KEY"
```

Switch API gateway or model through these variables; code changes are unnecessary **when the gateway speaks the compatible chat-completions protocol**. API keys are transmitted in an Authorization header and are not written into the call log. Input and output text **are** stored in local logs; do not submit sensitive personal data without appropriate safeguards.

## Running the CLI

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

# 8. Only when SQLite was selected: execute SQL in a real isolated SQLite database
python -m dba_agent.cli sql SESSION_UUID --verify-sqlite
```

Note: steps 7 and 8 are alternatives, not successive commands: SQL generation consumes the `APPROVED` state. To request real SQLite verification, use `--verify-sqlite` on the **first** `sql` command.

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
- `dba_agent/sql.py`: lexical coverage and SQLite execution checks.
- `dba_agent/cli.py`: command-line interface.
- `dba_agent/prompts/`: human-readable prompts for each model task.
- `tests/`: deterministic offline tests, including executable SQLite SQL.
- `docs/implementation-guide.md`: detailed architecture and explanation.

To support another API protocol, create a new transport adapter implementing the interface of `LLMClient` rather than altering the stage logic. For production deployment, add database-backed concurrency controls, credential isolation, stronger model/schema validation, and real-DBMS execution for each dialect.

## Tests and sample run

```bash
python -m unittest discover -v
```

The test suite uses an injected scripted model (not a real LLM) and validates actual SQLite DDL/DML execution inside an in-memory database. It also checks reloading state, guard conditions, follow-up requirement, revision invalidation, failed-model rollback, and repair-loop behavior. See `tests/test_pipeline.py` for the complete runnable offline example.

## Assignment tracking

The implementation covers the six required workflow stages at a functional prototype level, including persistence, external prompts, provider configuration and local logs. **Still needed before final submission:** an official end-to-end scenario run, the max-three-page architecture report, a genuine critique of at least three design flaws and remediations (or an account of checks performed), and executable verification against the actual chosen DBMS when not SQLite. Optional +15% bonus for an automatic repair loop with a real DBMS has only been exercised for SQLite; no assertion is made for other systems.
