"""Deterministic checks and statement-scoped repairs for generated SQL."""
from __future__ import annotations

import re
import sqlite3
from time import monotonic
from typing import Any

from .session import StateError
from .sql import sqlite_connection
from .sql_statements import CREATE_TABLE, INSERT, QUALIFIED, REFERENCES, split_sql, table_name


class SQLConflict(StateError):
    def __init__(self, message: str, file: str, statement: int | None = None, *,
                 table: str | None = None, related: tuple[str, ...] = ()):
        super().__init__(message)
        self.file = file
        self.statement = statement
        self.table = table
        self.related = related


_UNSAFE_VALIDATION = re.compile(
    r"(?:^|\n)[ \t]*(?:\\|:[a-z]|!!)"
    r"|^DELIMITER\b|/\*(?:M)?!"
    r"|^GO\s+\d+"
    r"|^PRAGMA\s+(?:\w+\.)?DEFER_FOREIGN_KEYS\b"
    r"|^ALTER\s+TABLE\b.*\b(?:NOCHECK|DISABLE\s+(?:TRIGGER|CONSTRAINT)|NOT\s+VALID)\b"
    r"|\bNOT\s+ENFORCED\b"
    r"|^SET\b.*\b(?:FOREIGN_KEY_CHECKS|UNIQUE_CHECKS|CHECK_CONSTRAINT_CHECKS|SQL_MODE|SESSION_REPLICATION_ROLE|IMPLICIT_TRANSACTIONS)\b"
    r"|^SET\s+ANSI_WARNINGS\s+OFF\b|\bENFORCE\s+KEYS\s*=\s*OFF\b"
    r"|\bIGNORE_DUP_KEY\s*=\s*ON\b|\bON\s+CONFLICT\s+(?:IGNORE|REPLACE)\b"
    r"|^INSERT\b.*\b(?:ON\s+CONFLICT\b.*\bDO\s+(?:NOTHING|UPDATE)|ON\s+DUPLICATE\s+KEY\s+UPDATE)\b"
    r"|^INSERT\s+(?:IGNORE|OR\s+(?:IGNORE|REPLACE))\b|^REPLACE\b"
    r"|^ROLLBACK(?!\s+(?:TRAN(?:SACTION)?\s+)?TO\b)\b",
    re.I | re.S,
)


class SQLArtifacts:
    def __init__(self, schema: str, seed: str, dbms: str):
        self.dbms = dbms
        self.sources = {"schema": schema, "seed": seed}
        self.statements = {file: split_sql(source, dbms) for file, source in self.sources.items()}

    def table_identifiers(self) -> dict[str, str]:
        tables = {}
        for statement in self.statements["schema"]:
            if match := CREATE_TABLE.match(statement.code):
                tables[table_name(match[1])] = match[1]
        return tables

    def preflight(self, tables: list[str]) -> None:
        for file, statements in self.statements.items():
            transaction = None
            for index, statement in enumerate(statements):
                code = statement.keywords
                if _UNSAFE_VALIDATION.search(code):
                    raise SQLConflict("Use plain SQL with constraint enforcement and without ignored writes or client directives.",
                                      file, index)
                if self.dbms == "MySQL/MariaDB" and CREATE_TABLE.match(statement.code):
                    if len(REFERENCES.findall(statement.code)) > len(re.findall(r"\bFOREIGN\s+KEY\b", code, re.I)):
                        raise SQLConflict("Declare MySQL/MariaDB references with explicit table-level FOREIGN KEY constraints.",
                                          file, index)
                    if re.search(r"\bENGINE\s*=?\s*(?!INNODB\b)[A-Za-z_]\w*\b", code.rsplit(")", 1)[-1], re.I):
                        raise SQLConflict("Use InnoDB to enforce foreign keys and transactions.", file, index)
                if re.match(r"^(?:START\s+TRANSACTION\b|BEGIN\s+TRAN(?:SACTION)?\b|BEGIN(?:\s+(?:DEFERRED|IMMEDIATE|EXCLUSIVE|WORK))?\s*;?\s*$)", code, re.I):
                    transaction = index
                elif re.match(r"^COMMIT\b", code, re.I) or (self.dbms in {"SQLite", "PostgreSQL"} and
                        re.match(r"^END(?:\s+(?:TRANSACTION|WORK))?\s*;?\s*$", code, re.I)):
                    transaction = None
            if transaction is not None:
                raise SQLConflict("The script leaves a transaction open. Commit it in the same file.", file, transaction)
        inserts = {stmt.table for stmt in self.statements["seed"] if INSERT.match(stmt.code)}
        created = self.table_identifiers()
        for table in tables:
            if table.casefold() not in created:
                raise SQLConflict(f"schema.sql does not create {table}", "schema", table=table.casefold())
            if table.casefold() not in inserts:
                raise SQLConflict(f"seed.sql does not populate {table}", "seed", table=table.casefold())

    def repair_context(self, conflict: SQLConflict, design: dict[str, Any]) -> dict[str, Any]:
        excerpts = {}
        editable = []

        def include(file: str, index: int, edit: bool = False) -> None:
            key = f"{file}:{index + 1}"
            excerpts[key] = self.statements[file][index].text
            if edit and key not in editable:
                editable.append(key)

        error = str(conflict)
        fk_error = re.search(r"foreign.key|referential", error, re.I)
        table = conflict.table
        index = conflict.statement
        if index is not None:
            table = table or self.statements[conflict.file][index].table
            if table is None and fk_error and conflict.file == "seed":
                # Deferred PostgreSQL failures can report the table on COMMIT rather than on INSERT.
                if match := re.search(rf"on table ({QUALIFIED}) violates foreign key", error, re.I):
                    table = table_name(match[1])
                    index = next((i for i in range(index - 1, -1, -1)
                                  if self.statements["seed"][i].table == table), index)
            include(conflict.file, index, edit=True)
        elif table:
            editable.append(f"append:{conflict.file}")

        schema_defect = "foreign key mismatch" in error.lower()
        if self.dbms == "SQLite" and conflict.file == "seed" and table:
            if missing := re.search(rf"no such table: ({QUALIFIED})", error, re.I):
                schema_defect = table_name(missing[1]) != table
        missing_seed = conflict.file == "seed" and index is None
        related = set(conflict.related)
        if fk_error:
            related.update(table_name(match[1]) for match in REFERENCES.finditer(error))
            if match := re.search(rf"is not present in table ({QUALIFIED})", error, re.I):
                related.add(table_name(match[1]))
        if (fk_error or missing_seed) and not related:
            for statement in self.statements["schema"]:
                if statement.table == table:
                    related.update(table_name(match[1]) for match in REFERENCES.finditer(statement.code))
        for schema_index, statement in enumerate(self.statements["schema"]):
            if statement.table in related | {table} and statement.table is not None:
                if (CREATE_TABLE.match(statement.code) or
                        ((fk_error or missing_seed) and REFERENCES.search(statement.code)) or
                        (re.search(r"unique|duplicate|primary key", error, re.I) and
                         re.search(r"\bUNIQUE\b", statement.code, re.I))):
                    include("schema", schema_index, edit=schema_defect)

        if conflict.file == "seed" and (fk_error or missing_seed):
            # A parent insert gives the model an anchor for repairing a key or insertion order.
            for target in sorted(related):
                for seed_index, statement in reversed(list(enumerate(self.statements["seed"]))):
                    if statement.table == target and seed_index != index and INSERT.match(statement.code):
                        include("seed", seed_index, edit=bool(fk_error))
                        break

        context = {"dbms": self.dbms, "validation_error": error, "statements": excerpts, "editable": editable}
        if table:
            context["table"] = table
        if table and (conflict.file == "schema" or conflict.statement is None or schema_defect):
            context["table_design"] = next((t for t in design["tables"] if t["name"].casefold() == table), {})
        return context

    def apply(self, response: dict[str, Any], editable: list[str]) -> None:
        patches = response.get("patches")
        if (not isinstance(patches, dict) or not patches or not set(patches) <= set(editable) or
                not all(isinstance(value, str) for value in patches.values())):
            raise StateError("Return a patches object with SQL strings for one or more editable IDs.")
        sources = self.sources.copy()
        for file, statements in self.statements.items():
            for index, statement in reversed(list(enumerate(statements, start=1))):
                key = f"{file}:{index}"
                if key in patches:
                    source = sources[file]
                    sources[file] = source[:statement.start] + patches[key].strip() + source[statement.end:]
            if fragment := patches.get(f"append:{file}", "").strip():
                sources[file] += "\n" + fragment
        if sources == self.sources:
            raise StateError("The patch did not change either script.")
        for file, source in sources.items():
            if source != self.sources[file]:
                self.statements[file] = split_sql(source, self.dbms)
        self.sources = sources


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _storage_classes(declared: str) -> str:
    declared = declared.upper().partition("(")[0].strip()
    if "INT" in declared:
        return "'integer'"
    if any(word in declared for word in ("CHAR", "CLOB", "TEXT")):
        return "'text'"
    if declared == "BLOB":
        return "'blob'"
    if (any(word in declared for word in ("REAL", "FLOA", "DOUB")) or
            declared in {"NUMERIC", "DECIMAL", "NUMBER", "BOOLEAN", "BOOL"}):
        return "'integer', 'real'"
    return ""


def _sqlite_type_checks(connection: sqlite3.Connection, tables: list[str]) -> None:
    # SQLite affinity allows incompatible storage classes in ordinary tables.
    # Temporary guards check stored values, keeping valid SQLite coercions and defaults.
    for table_index, table in enumerate(tables):
        cases = []
        for _, name, declared, _, _, primary_key, _ in connection.execute(f"PRAGMA table_xinfo({_quote(table)})"):
            column = f"NEW.{_quote(name)}"
            label = f"{table}.{name}".replace("'", "''")
            if primary_key:
                cases.append(f"WHEN {column} IS NULL THEN RAISE(ABORT, 'NULL primary key: {label}')")
            if types := _storage_classes(declared):
                cases.append(f"WHEN typeof({column}) NOT IN ('null', {types}) "
                             f"THEN RAISE(ABORT, 'Incompatible SQLite type for {label}')")
        if cases:
            for event in ("INSERT", "UPDATE"):
                connection.execute(f"CREATE TEMP TRIGGER {_quote(f'_seed_check_{table_index}_{event}')} "
                                   f"AFTER {event} ON {_quote(table)} BEGIN SELECT CASE {' '.join(cases)} END; END")


def _sqlite_fk_parents(connection: sqlite3.Connection, table: str, source: str) -> tuple[str, ...]:
    """Replay a failed write in a savepoint to identify its violated foreign keys."""
    check = f"PRAGMA foreign_key_check({_quote(table)})"
    try:
        before = set(connection.execute(check)) if connection.in_transaction else set()
        connection.execute("SAVEPOINT _dba_fk_probe")
        try:
            connection.execute("PRAGMA defer_foreign_keys=ON")
            connection.execute(source)
            return tuple(sorted({parent.casefold() for child, row, parent, fk in connection.execute(check)
                                 if (child, row, parent, fk) not in before}))
        finally:
            connection.execute("ROLLBACK TO _dba_fk_probe")
            connection.execute("RELEASE _dba_fk_probe")
    except sqlite3.Error:
        return ()


def validate_sqlite_seed(artifacts: SQLArtifacts, tables: list[str]) -> None:
    with sqlite_connection(allow_fk_probe=True) as connection:
        connection.isolation_level = None
        deadline = monotonic() + 30
        connection.set_progress_handler(lambda: int(monotonic() >= deadline), 10_000)
        deferred = any(re.search(r"\bINITIALLY\s+DEFERRED\b", stmt.keywords, re.I)
                       for stmt in artifacts.statements["schema"])
        violations_by_insert = {}
        for file, statements in artifacts.statements.items():
            for index, statement in enumerate(statements):
                table = statement.table
                try:
                    connection.execute(statement.text)
                    if deferred and table and file == "seed" and connection.in_transaction:
                        for violation in connection.execute(f"PRAGMA foreign_key_check({_quote(table)})"):
                            violations_by_insert.setdefault(violation, index)
                    if not connection.in_transaction:
                        violations_by_insert.clear()
                except sqlite3.Error as exc:
                    related = ()
                    if str(exc) == "FOREIGN KEY constraint failed" and connection.in_transaction and re.match(
                            r"^(?:COMMIT|END|RELEASE)\b", statement.keywords, re.I):
                        # A deferred FK can fail at COMMIT. Recover the originating child INSERT.
                        violation = connection.execute("PRAGMA foreign_key_check").fetchone()
                        if violation:
                            table, _, parent, _ = violation
                            table, related = table.casefold(), (parent.casefold(),)
                            index = violations_by_insert.get(violation, index)
                    elif str(exc) == "FOREIGN KEY constraint failed" and table:
                        related = _sqlite_fk_parents(connection, table, statement.text)
                    raise SQLConflict(f"{file}.sql: {exc}", file, index, table=table, related=related) from exc
            if connection.in_transaction:
                raise SQLConflict(f"{file}.sql leaves a transaction open", file, len(statements) - 1)
            if file == "schema":
                _sqlite_type_checks(connection, tables)
        for table in tables:
            if connection.execute(f"SELECT 1 FROM {_quote(table)} LIMIT 1").fetchone() is None:
                index = next(i for i, stmt in enumerate(artifacts.statements["seed"]) if stmt.table == table.casefold())
                raise SQLConflict(f"seed.sql left {table} empty", "seed", index, table=table.casefold())
