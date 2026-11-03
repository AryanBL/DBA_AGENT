# DBA Agent

An incremental implementation of the LLM-powered database design assistant
described in `dba_agent_project.pdf`.

## Current implementation

The domain layer currently supports persistent sessions, the intake and
requirements-interview lifecycle, and DBMS selection. A DBMS recommendation is
accepted only after all seven interview categories and a follow-up round have
been completed.

The DBMS selection record contains the selected engine, a comparison of
PostgreSQL, MySQL/MariaDB, SQLite, and SQL Server, a rejection reason for every
alternative, and evidence linking the decision to the interview categories.
The record can be rendered as `dbms-choice.md` with
`Session.dbms_choice_markdown()`.

## Run tests

```bash
python -m unittest discover -v
```

The next workflow stage will build the design documents from the structured
requirements and DBMS decision.
