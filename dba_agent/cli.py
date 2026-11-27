"""Interactive workspace and scriptable commands for the DBA Agent."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .config import Config
from .service import AgentService
from .session import Stage, StateError


def show(session) -> None:
    print(f"Session: {session.session_id}\nStage: {session.state.value}\nVersion: {session.active_version}")
    if session.state == Stage.INTERVIEWING and session.pending_questions:
        print("\nPending interview questions:")
        for i, question in enumerate(session.pending_questions, 1):
            print(f"  {i}. {question}")
    elif session.state == Stage.DESIGN_READY:
        print("\nDesign documents generated. Review output/<session-id>/v<version>/ and then revise or approve.")
    elif session.state == Stage.APPROVED:
        print("\nApproved. Run the sql command to generate SQL.")
    elif session.state == Stage.SQL_GENERATED:
        selected = session.dbms_choice.get("selected")
        next_step = ("Use execute-sql with a database file, or verify-sqlite for an in-memory check." if selected == "SQLite" else
                     "Use execute-sql to run the saved files.")
        print(f"\nSQL generated for the approved version. {next_step}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DBA Agent: structured database-design assistant")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("interactive", help="open the guided terminal workspace (default in a terminal)")
    remove = sub.add_parser("delete", help="delete one saved session")
    remove.add_argument("session_id")
    start = sub.add_parser("new", help="create a new session from a natural-language description")
    start.add_argument("description", help="system description in plain text")
    advance = sub.add_parser("continue", help="resume incomplete LLM stages and show questions")
    advance.add_argument("session_id")
    status = sub.add_parser("status", help="read existing session without model calls")
    status.add_argument("session_id")
    answer = sub.add_parser("answer", help="answer outstanding questions interactively or using JSON file")
    answer.add_argument("session_id")
    answer.add_argument("--json", help="path to JSON mapping exact question text to answer")
    revise = sub.add_parser("revise", help="apply a user revision across the design documents")
    revise.add_argument("session_id")
    revise.add_argument("request")
    approve = sub.add_parser("approve", help="approve current design version")
    approve.add_argument("session_id")
    sql = sub.add_parser("sql", help="generate SQL only for explicitly approved design")
    sql.add_argument("session_id")
    execute = sub.add_parser("execute-sql", help="run generated SQL in an existing container or SQLite database file")
    execute.add_argument("session_id")
    execute.add_argument("--container", default="", help="name or ID of an already-running server container")
    execute.add_argument("--database", required=True, help="server database name, or SQLite file path")
    execute.add_argument("--user", default="", help="server database username")
    verify = sub.add_parser("verify-sqlite", help="execute generated SQLite files in a fresh in-memory database")
    verify.add_argument("session_id")
    args = parser.parse_args(argv)
    if args.command is None and not sys.stdin.isatty():
        parser.error("choose a command or use 'interactive' to open the workspace")
    try:
        agent = AgentService(Config.from_env())
        if args.command in (None, "interactive"):
            from .terminal import run

            return run(agent)
        elif args.command == "delete":
            agent.delete(args.session_id)
            print(f"Deleted session {args.session_id}")
        elif args.command == "new":
            show(agent.create(args.description))
        elif args.command == "continue":
            show(agent.advance(args.session_id))
        elif args.command == "status":
            show(agent.get(args.session_id))
        elif args.command == "answer":
            existing = agent.get(args.session_id)
            if args.json:
                with open(args.json, encoding="utf-8") as fh:
                    answers = json.load(fh)
            else:
                answers = {q: input(f"{q}\n> ").strip() for q in existing.pending_questions}
            show(agent.answer(args.session_id, answers))
        elif args.command == "revise":
            show(agent.revise(args.session_id, args.request))
        elif args.command == "approve":
            show(agent.approve(args.session_id))
        elif args.command == "sql":
            print(json.dumps(agent.generate_sql(args.session_id), indent=2))
        elif args.command == "execute-sql":
            print(json.dumps(agent.execute_sql(args.session_id, container=args.container,
                database=args.database, username=args.user, password=os.getenv("DBA_AGENT_SQL_PASSWORD", "")), indent=2))
        elif args.command == "verify-sqlite":
            print(json.dumps(agent.verify_sqlite(args.session_id), indent=2))
        return 0
    except (StateError, ValueError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
