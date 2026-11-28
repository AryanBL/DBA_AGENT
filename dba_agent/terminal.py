"""Full-screen conversation workspace for the persisted design workflow."""
from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path
from typing import Callable

from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, LoadingIndicator, OptionList, RichLog, Static, TextArea

from .service import AgentService
from .session import Session, Stage


HELP = """**Commands**

`/new` Start a session · `/sessions` Focus saved sessions · `/continue` Resume a saved stage

`/review` Browse generated files · `/revise your request` Request a revision

`/approve` Approve the current version · `/sql` Generate SQL files

`/execute-sql` Create a database and load the generated SQL

`/execute-sql CONTAINER DATABASE USER` Run saved server SQL with `DBA_AGENT_SQL_PASSWORD`

`/execute-sql DATABASE_FILE` Run saved SQLite SQL into a file

`/sql-commands` Show table listing and row preview commands from the last successful container run

`/verify-sqlite` Execute saved SQLite files in memory

`/delete` Delete selected session · `/help` Show commands

Enter sends. Shift+Enter inserts a newline. Ctrl+B toggles the sidebar.
Use Copy on a message to copy its text; generated commands have separate copy buttons.
"""


class Composer(TextArea):
    BINDINGS = [Binding("enter", "send", "Send", priority=True),
                Binding("shift+enter", "newline", "New line", show=False, priority=True)]

    def action_send(self) -> None:
        self.app.action_send()

    def action_newline(self) -> None:
        self.insert("\n")


class MessageCard(Vertical):
    """Conversation text with clipboard actions for the message and any commands."""

    def __init__(self, role: str, content: str, commands: dict[str, str] | None = None):
        super().__init__(classes=f"message {role}")
        self.role = role
        self.content = content
        self.commands = commands or {}

    def compose(self) -> ComposeResult:
        with Horizontal(classes="message-heading"):
            yield Static(self.role.upper(), classes="message-role")
            yield Button("Copy", name="message", classes="copy-message")
        yield Static(Markdown(self.content), classes="message-content")
        if self.commands:
            with Horizontal(classes="command-actions"):
                yield Button("Copy table command", name="list_tables", classes="copy-command")
                yield Button("Copy row command", name="preview_rows", classes="copy-command")

    @on(Button.Pressed)
    def copy(self, event: Button.Pressed) -> None:
        event.stop()
        label = event.button.name or "message"
        self.app.copy_to_clipboard(self.content if label == "message" else self.commands[label])
        self.app.notify("Copied to clipboard")


class Confirm(ModalScreen[bool]):
    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(Text(self.question))
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Confirm", variant="primary", id="confirm")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    @on(Button.Pressed)
    def selected(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def key_escape(self) -> None:
        self.dismiss(False)


class SQLConnection(ModalScreen[tuple[str, str, str, str] | None]):
    fields = (("container", "Docker container"), ("database", "Database name"), ("username", "Database username"))

    def __init__(self, target: tuple[str, str, str], *, needs_password: bool):
        super().__init__()
        self.target = target
        self.needs_password = needs_password

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="sql-connection-box"):
            yield Static("Execute schema.sql and seed.sql")
            for (name, label), value in zip(self.fields, self.target):
                yield Static(label)
                yield Input(value=value, id=f"sql-{name}")
            if self.needs_password:
                yield Static("Database password")
                yield Input(password=True, id="sql-password")
            yield Static("", id="sql-connection-error")
            with Horizontal():
                yield Button("Cancel", id="sql-cancel")
                yield Button("Run SQL", id="sql-run", variant="primary")

    def on_mount(self) -> None:
        field = "password" if self.needs_password and all(self.target) else "container"
        self.query_one(f"#sql-{field}", Input).focus()

    @on(Button.Pressed, "#sql-run")
    @on(Input.Submitted)
    def submit(self) -> None:
        error = self.query_one("#sql-connection-error", Static)
        values = []
        for name, label in self.fields:
            field = self.query_one(f"#sql-{name}", Input)
            if not field.value.strip():
                error.update(f"Enter a value for {label.lower()}.")
                field.focus()
                return
            values.append(field.value.strip())
        password = ""
        if self.needs_password:
            field = self.query_one("#sql-password", Input)
            password = field.value
            if not password:
                error.update("Enter the database password.")
                field.focus()
                return
            field.clear()
        self.dismiss((values[0], values[1], values[2], password))

    @on(Button.Pressed, "#sql-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def key_escape(self) -> None:
        self.cancel()


class Preview(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, name: str, content: str):
        super().__init__()
        self.filename, self.content = name, content

    def compose(self) -> ComposeResult:
        with Vertical(id="preview-box"):
            yield Static(Text(self.filename), id="preview-title")
            yield RichLog(wrap=True, id="preview-content")
            yield Button("Close · Esc", id="close")

    def on_mount(self) -> None:
        content = Syntax(self.content, "sql", word_wrap=True) if self.filename.endswith(".sql") else Markdown(self.content)
        self.query_one(RichLog).write(content)
        self.query_one(RichLog).focus()

    def action_close(self) -> None:
        self.dismiss()

    @on(Button.Pressed)
    def close(self) -> None:
        self.dismiss()


class Workspace(App):
    TITLE = "DBA Agent"
    CSS = """
    Screen { background: #101317; color: #dce1e7; }
    #top { height: 3; padding: 1 2; background: #171c22; }
    #brand { width: 1fr; color: #68d5bf; text-style: bold; }
    #model { width: auto; color: #939faa; }
    #body { height: 1fr; }
    #usage { width: 32; text-align: right; color: #68d5bf; }
    #sidebar { width: 30; padding: 1; background: #171c22; border-right: solid #28313b; }
    .section { color: #939faa; margin: 0 1; text-style: bold; }
    #new { width: 100%; height: 3; }
    #sessions { height: 1fr; border: none; background: #171c22; }
    #files { height: 7; border: none; background: #171c22; }
    OptionList > .option-list--option-highlighted { background: #29433f; color: #a4f2df; }
    #session-info { height: auto; margin: 1; color: #939faa; }
    #main { width: 1fr; }
    #stage { height: 3; padding: 1 3; color: #939faa; }
    #conversation { height: 1fr; padding: 0 3; }
    .message { height: auto; margin-bottom: 1; padding: 1 2; }
    .message-heading { height: 1; }
    .message-role { width: 1fr; text-style: bold; }
    .message Button { width: auto; min-width: 6; height: 1; min-height: 1; border: none; padding: 0 1; background: #29433f; color: #a4f2df; }
    .message-content { height: auto; }
    .command-actions { height: 1; margin-top: 1; }
    .command-actions Button { margin-right: 1; }
    .assistant { border-left: thick #68d5bf; background: #161d22; }
    .user { border-left: thick #8c9fe5; background: #1c202d; }
    .error { border-left: thick #f18d8d; background: #2a1d24; }
    #welcome { height: auto; margin: 3 2; padding: 2 3; }
    #welcome-title { color: #68d5bf; text-style: bold; height: 3; }
    #welcome-copy { color: #939faa; height: auto; }
    #busy { height: 1; display: none; color: #68d5bf; }
    #composer-box { height: 9; margin: 0 3 1 3; padding: 0 1; border: round #3c6c65; background: #1b2229; }
    #composer-box:focus-within { border: round #68d5bf; }
    #input-hint { height: 1; color: #68d5bf; }
    #composer { height: 1fr; border: none; background: #1b2229; }
    #input-bottom { height: 1; }
    #shortcuts { width: 1fr; color: #939faa; }
    #send { min-width: 10; width: 10; height: 1; min-height: 1; border: none; background: #29433f; color: #a4f2df; }
    Footer { background: #171c22; }
    Confirm, Preview, SQLConnection { align: center middle; background: #000000 65%; }
    #confirm-box { width: 65; height: auto; padding: 2; border: round #68d5bf; background: #1b2229; }
    #confirm-box Static { height: auto; margin-bottom: 1; }
    #confirm-box Horizontal { height: 3; align-horizontal: right; }
    #confirm-box Button { margin-left: 1; }
    #sql-connection-box { width: 65; max-width: 95%; height: auto; max-height: 95%; padding: 1 2; border: round #68d5bf; background: #1b2229; }
    #sql-connection-box Static { height: auto; }
    #sql-connection-error { color: #f18d8d; min-height: 1; }
    #sql-connection-box Horizontal { height: 3; align-horizontal: right; }
    #sql-connection-box Button { margin-left: 1; }
    #preview-box { width: 90%; height: 90%; padding: 1 2; border: round #68d5bf; background: #171c22; }
    #preview-title { height: 2; color: #68d5bf; }
    #preview-content { height: 1fr; background: #171c22; }
    """
    BINDINGS = [Binding("ctrl+n", "new_session", "New"), Binding("ctrl+b", "sidebar", "Sidebar"),
                Binding("ctrl+l", "sessions", "Sessions"), Binding("ctrl+q", "quit", "Quit")]

    def __init__(self, agent: AgentService):
        super().__init__()
        self.agent = agent
        self.session: Session | None = None
        self.saved: list[Session] = []
        self.artifacts: list[tuple[str, str]] = []
        self.answers: dict[str, str] = {}
        self.busy = False
        self.submitting = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("◈  DBA AGENT", id="brand")
            yield Static(Text(self.agent.config.model), id="model")
            yield Static("Tokens: 0", id="usage")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Button("＋ New session", id="new")
                yield Static("SESSIONS", classes="section")
                yield OptionList(id="sessions")
                yield Static("", id="session-info")
                yield Static("GENERATED FILES", classes="section")
                yield OptionList(id="files")
            with Vertical(id="main"):
                yield Static("INTAKE  /  INTERVIEW  /  DESIGN  /  APPROVAL  /  SQL", id="stage")
                with VerticalScroll(id="conversation"):
                    with Vertical(id="welcome"):
                        yield Static("Design your next database.", id="welcome-title")
                        yield Static("Describe a system below or resume a saved session.\n\nRequirements → interview → relational design → SQL\n\nType /help for commands.", id="welcome-copy")
                yield LoadingIndicator(id="busy")
                with Vertical(id="composer-box"):
                    yield Static("NEW SESSION · Describe your database system", id="input-hint")
                    yield Composer(id="composer", soft_wrap=True)
                    with Horizontal(id="input-bottom"):
                        yield Static("Enter send · Shift+Enter newline · /help", id="shortcuts")
                        yield Button("Send ↵", id="send")
        yield Footer()

    async def on_mount(self) -> None:
        self.refresh_sessions()
        self.set_interval(1, self.refresh_usage)
        self.query_one(Composer).focus()

    def refresh_usage(self) -> None:
        if self.session:
            try:
                usage = self.query_one("#usage", Static)
                count = self.agent.get(self.session.session_id).metadata.get("usage", {}).get("total_tokens", 0)
                usage.update(f"Tokens: {count:,}")
            except (NoMatches, ValueError, OSError):
                pass

    def on_resize(self, event: events.Resize) -> None:
        if self.query("#sidebar"):
            self.query_one("#sidebar").display = event.size.width >= 90

    def refresh_sessions(self) -> None:
        self.saved = []
        for path in self.agent.store.root.glob("*.json"):
            try:
                self.saved.append(self.agent.get(path.stem))
            except (ValueError, OSError) as exc:
                self.notify(f"Could not load {path.name}: {exc}", severity="warning")
        self.saved.sort(key=lambda session: session.updated_at, reverse=True)
        listing = self.query_one("#sessions", OptionList)
        listing.clear_options()
        listing.add_options([Text(f"{' '.join(s.intake_text.split())[:25]}\nv{s.active_version} · {s.state.value.replace('_', ' ').lower()}") for s in self.saved])
        if self.saved:
            listing.highlighted = 0

    async def message(self, role: str, content: str, commands: dict[str, str] | None = None) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        if self.query("#welcome"):
            await self.query_one("#welcome").remove()
        await conversation.mount(MessageCard(role, content, commands))
        conversation.scroll_end(animate=False)

    async def show_session(self, session: Session, history: bool = False) -> None:
        self.session = session
        self.refresh_usage()
        if history:
            self.answers = {}
            await self.query_one("#conversation").remove_children()
            await self.message("user", session.intake_text)
            for round_ in session.interview_rounds:
                for question in round_["questions"]:
                    await self.message("assistant", question)
                    await self.message("user", round_["answers"][question])
            for revision in session.revision_history:
                await self.message("user", revision["request"])
                await self.message("assistant", revision["reason"])
        self.query_one("#stage", Static).update(Text(f"{session.state.value.replace('_', ' ')}  /  v{session.active_version}  /  {session.dbms_choice.get('selected', 'DBMS pending')}"))
        self.query_one("#session-info", Static).update(Text(f"Session\n{session.session_id}"))
        self.artifacts = sorted(session.design.artifacts.items())
        files = self.query_one("#files", OptionList)
        files.clear_options()
        files.add_options([Text(name) for name, _ in self.artifacts])
        if self.artifacts:
            files.highlighted = 0
        hint = "Use /continue to resume this stage"
        if session.state == Stage.INTERVIEWING and session.pending_questions:
            unanswered = [q for q in session.pending_questions if q not in self.answers]
            if unanswered:
                hint = f"INTERVIEW · Round {len(session.interview_rounds) + 1} · Answer {len(self.answers) + 1}/{len(session.pending_questions)}"
                await self.message("assistant", unanswered[0])
        elif session.state == Stage.DESIGN_READY:
            hint = "DESIGN READY · Describe a revision or use /approve"
            await self.message("assistant", "Your design is ready. Select a generated file to review it, describe a revision, or use `/approve`.")
        elif session.state == Stage.APPROVED:
            hint = "APPROVED · Use /sql to generate SQL"
        elif session.state == Stage.SQL_GENERATED:
            selected = session.dbms_choice.get("selected")
            hint = ("SQL GENERATED · Use /execute-sql or /verify-sqlite" if selected == "SQLite" else
                    "SQL GENERATED · Use /execute-sql or review files")
        self.query_one("#input-hint", Static).update(hint)
        self.refresh_sessions()

    @on(OptionList.OptionSelected, "#sessions")
    async def select_session(self, event: OptionList.OptionSelected) -> None:
        if self.busy or self.answers:
            self.notify("Finish the current operation or answer round first.", severity="warning")
            return
        try:
            await self.show_session(self.agent.get(self.saved[event.option_index].session_id), history=True)
            self.query_one(Composer).focus()
        except (ValueError, OSError) as exc:
            await self.message("error", str(exc))

    @on(OptionList.OptionSelected, "#files")
    def preview_file(self, event: OptionList.OptionSelected) -> None:
        name, filename = self.artifacts[event.option_index]
        try:
            self.push_screen(Preview(name, Path(filename).read_text(encoding="utf-8")))
        except OSError as exc:
            self.notify(str(exc), severity="error")

    def action_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display

    def action_sessions(self) -> None:
        self.query_one("#sidebar").display = True
        self.query_one("#sessions").focus()

    def action_new_session(self) -> None:
        if self.busy or self.answers:
            self.notify("Finish the current operation or answer round first.", severity="warning")
            return
        self.reset_session()

    @work
    async def reset_session(self) -> None:
        self.session = None
        self.artifacts = []
        self.query_one("#files", OptionList).clear_options()
        self.query_one("#session-info", Static).update("")
        self.query_one("#stage", Static).update("NEW SESSION")
        self.query_one("#input-hint", Static).update("Describe your database system")
        await self.query_one("#conversation").remove_children()
        await self.message("assistant", "What system would you like to design a database for?")
        self.query_one(Composer).clear()
        self.query_one(Composer).focus()

    @on(Button.Pressed, "#new")
    def new_button(self) -> None:
        self.action_new_session()

    @on(Button.Pressed, "#send")
    def send_button(self) -> None:
        self.action_send()

    def action_send(self) -> None:
        if self.busy or self.submitting:
            return
        self.submitting = True
        self.submit()

    @work(group="submit")
    async def submit(self) -> None:
        try:
            await self.process_input()
        finally:
            self.submitting = False

    async def process_input(self) -> None:
        composer = self.query_one(Composer)
        text = composer.text.strip()
        if not text:
            return
        composer.clear()
        if text.startswith("/"):
            await self.command(text)
            return
        await self.message("user", text)
        if self.session is None:
            self.operation("Reading requirements…", lambda: self.agent.create(text))
        elif self.session.state == Stage.INTERVIEWING and self.session.pending_questions:
            question = next(q for q in self.session.pending_questions if q not in self.answers)
            self.answers[question] = text
            if len(self.answers) == len(self.session.pending_questions):
                answers = dict(self.answers)
                self.operation("Assessing answers and preparing the design…", lambda: self.agent.answer(self.session.session_id, answers))
            else:
                await self.show_session(self.session)
        elif self.session.state in (Stage.DESIGN_READY, Stage.APPROVED, Stage.SQL_GENERATED):
            self.operation("Revising the design…", lambda: self.agent.revise(self.session.session_id, text))
        else:
            await self.message("assistant", "Use `/continue` to finish the saved stage.")

    async def command(self, text: str) -> None:
        command, _, argument = text.partition(" ")
        if command == "/help":
            await self.message("assistant", HELP)
        elif command == "/new":
            self.action_new_session()
        elif command == "/sessions":
            self.action_sessions()
        elif self.session is None:
            await self.message("assistant", "Select a saved session or describe a new system first.")
        elif command == "/review":
            self.query_one("#sidebar").display = True
            self.query_one("#files").focus()
        elif command == "/continue":
            if self.answers:
                await self.message("assistant", "Finish the current answer round first.")
            else:
                self.operation("Resuming the workflow…", lambda: self.agent.advance(self.session.session_id))
        elif command == "/revise" and argument.strip():
            if self.session.state not in (Stage.DESIGN_READY, Stage.APPROVED, Stage.SQL_GENERATED):
                await self.message("error", "A completed design is required before revision.")
                return
            await self.message("user", argument)
            self.operation("Revising the design…", lambda: self.agent.revise(self.session.session_id, argument))
        elif command == "/approve":
            if self.session.state != Stage.DESIGN_READY:
                await self.message("error", "Approval requires a completed design.")
                return
            sid, version = self.session.session_id, self.session.active_version
            self.push_screen(Confirm(f"Approve design v{version}? Review its generated files before confirming."),
                             lambda confirmed: self.operation("Approving design…", lambda: self.agent.approve(sid)) if confirmed else None)
        elif command == "/sql":
            if self.session.state != Stage.APPROVED:
                await self.message("error", "Approve the current design before generating SQL.")
                return
            self.operation("Generating SQL files…", lambda: self.agent.generate_sql(self.session.session_id))
        elif command == "/execute-sql":
            await self.execute_sql_command(self.session, argument)
        elif command == "/sql-commands":
            try:
                await self.show_sql_commands(self.agent.sql_inspection_commands(self.session.session_id))
            except ValueError as exc:
                await self.message("error", str(exc))
        elif command == "/verify-sqlite":
            self.operation("Verifying generated SQLite files…", lambda: self.agent.verify_sqlite(self.session.session_id))
        elif command == "/delete":
            sid = self.session.session_id
            self.push_screen(Confirm(f"Delete session {sid}? Generated files are retained."),
                             lambda confirmed: self.operation("Deleting session…", lambda: self.agent.delete(sid), deleting=True) if confirmed else None)
        else:
            await self.message("assistant", "Unknown command or missing revision text. Type `/help` to see commands.")

    async def execute_sql_command(self, session: Session, argument: str) -> None:
        if session.state != Stage.SQL_GENERATED:
            await self.message("error", "Generate the SQL files with `/sql` before executing them.")
            return

        def execute(container: str = "", database: str = "", username: str = "", password: str = "") -> None:
            self.operation("Executing generated SQL…", lambda: self.agent.execute_sql(
                session.session_id, container=container, database=database, username=username, password=password))

        if not argument.strip():
            execute()
            return
        if session.dbms_choice.get("selected") == "SQLite":
            execute(database=argument.strip())
            return

        try:
            parts = shlex.split(argument)
        except ValueError:
            await self.message("error", "Check the quotes in your connection arguments.")
            return
        if len(parts) != 3 or not all(part.strip() for part in parts):
            await self.message("error", "Use `/execute-sql` to create a database or `/execute-sql CONTAINER DATABASE USER` to load an existing one.")
            return

        target = (parts[0], parts[1], parts[2])
        env_password = os.getenv("DBA_AGENT_SQL_PASSWORD", "")
        if env_password:
            execute(*target, env_password)
            return

        def confirm(connection: tuple[str, str, str, str] | None) -> None:
            if connection is not None:
                container, database, username, password = connection
                execute(container, database, username, password)

        self.push_screen(SQLConnection(target, needs_password=True), confirm)

    async def show_sql_commands(self, commands: dict[str, str]) -> None:
        await self.message("assistant", "Run these in your shell and enter the database password when prompted."
            f"\n\nList tables\n\n```sh\n{commands['list_tables']}\n```"
            f"\n\nPreview up to 10 rows\n\n```sh\n{commands['preview_rows']}\n```", commands)

    def operation(self, label: str, call: Callable, deleting: bool = False) -> None:
        self.busy = True
        self.query_one("#busy").display = True
        self.query_one("#input-hint", Static).update(label)
        self.query_one(Composer).disabled = True
        self.query_one("#send", Button).disabled = True
        self.perform(call, deleting)

    @work(group="service")
    async def perform(self, call: Callable, deleting: bool) -> None:
        try:
            result = await asyncio.to_thread(call)
            self.answers = {}
            if deleting:
                self.reset_session()
                self.refresh_sessions()
            elif isinstance(result, Session):
                await self.show_session(result)
            else:
                await self.show_session(self.agent.get(self.session.session_id))
                if result.get("verified_sqlite"):
                    status = "SQLite execution verified."
                elif result.get("executed"):
                    status = f"SQL files executed.\n\nDatabase: {result['database']}" if "database" in result else "SQL files executed."
                    if result.get("container"):
                        status += f"\n\nContainer: {result['container']}"
                    if result.get("username"):
                        status += f"\n\nDatabase username: {result['username']}"
                else:
                    selected = self.session.dbms_choice.get("selected")
                    next_step = ("Use `/execute-sql` to create a database file, or `/verify-sqlite` to check them in memory." if selected == "SQLite" else
                                 "Use `/execute-sql` to start a local database container and load them.")
                    status = f"SQL files generated. {next_step}"
                await self.message("assistant", status + f"\n\nSchema: {result['schema']}\n\nSeed: {result['seed']}")
                if commands := result.get("inspection_commands"):
                    await self.show_sql_commands(commands)
        except Exception as exc:
            # Reload the checkpoint saved before subsequent model calls fail.
            if self.session:
                self.answers = {}
                try:
                    await self.show_session(self.agent.get(self.session.session_id))
                except (ValueError, OSError):
                    pass
            self.refresh_sessions()
            await self.message("error", str(exc))
        finally:
            self.busy = False
            self.query_one("#busy").display = False
            self.query_one(Composer).disabled = False
            self.query_one("#send", Button).disabled = False
            self.query_one(Composer).focus()

    def action_quit(self) -> None:
        if self.busy:
            self.notify("Wait for the current operation to finish before exiting.", severity="warning")
        elif self.answers:
            self.push_screen(Confirm("Exit and discard answers from this unfinished round? Completed rounds are saved."),
                             lambda confirmed: self.exit() if confirmed else None)
        else:
            self.exit()


def run(agent: AgentService) -> int:
    Workspace(agent).run()
    return 0
