"""Static SQL coverage checks and real isolated SQLite schema/seed execution."""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .session import StateError


def validate_sql_artifacts(schema: str, seed: str, tables: list[str]) -> None:
    """Conservative lexical coverage: not a full dialect parser or semantic proof."""
    if not isinstance(schema, str) or not isinstance(seed, str) or not schema.strip() or not seed.strip():
        raise StateError("both schema.sql and seed.sql are required")
    for table in tables:
        quoted = re.escape(table)
        qualifier = r'(?:(?:"?[A-Za-z_][A-Za-z_0-9]*"?|\[[A-Za-z_][A-Za-z_0-9]*\])\.)?'
        name = rf'["`\[]?{quoted}["`\]]?(?=\s|\(|;|$)'
        create = rf'\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{qualifier}{name}'
        insert = rf'\bINSERT\s+INTO\s+{qualifier}{name}'
        if not re.search(create, schema, re.IGNORECASE):
            raise StateError(f"schema.sql does not create {table}")
        if not re.search(insert, seed, re.IGNORECASE):
            raise StateError(f"seed.sql does not populate {table}")


def _check_sqlite_structure(connection: sqlite3.Connection, model: dict[str, Any]) -> None:
    """Read back the executed SQLite catalog, comparing columns, keys and indexes."""
    for table in model["tables"]:
        name = table["name"]  # validated by model.validate_design before this function
        actual = connection.execute(f'PRAGMA table_info("{name}")').fetchall()
        actual_columns = {col[1]: col for col in actual}
        expected_columns = {col["name"]: col for col in table["columns"]}
        if set(actual_columns) != set(expected_columns):
            raise StateError(f"SQLite columns differ from design for {name}: {set(actual_columns)} vs {set(expected_columns)}")
        for col_name, expected in expected_columns.items():
            actual_type = " ".join(actual_columns[col_name][2].upper().split())
            declared_type = " ".join(expected["type"].upper().split())
            if actual_type != declared_type:
                raise StateError(f"SQLite type mismatch for {name}.{col_name}: {actual_type} vs {declared_type}")
            if not expected["nullable"] and col_name not in table["primary_key"] and actual_columns[col_name][3] != 1:
                raise StateError(f"SQLite NOT NULL missing for {name}.{col_name}")
        actual_pk = [col[1] for col in sorted((col for col in actual if col[5] > 0), key=lambda c: c[5])]
        if actual_pk != table["primary_key"]:
            raise StateError(f"SQLite primary key mismatch for {name}: {actual_pk} vs {table['primary_key']}")

        raw_fks = connection.execute(f'PRAGMA foreign_key_list("{name}")').fetchall()
        grouped: dict[int, list[tuple]] = {}
        for row in raw_fks:
            grouped.setdefault(row[0], []).append(row)
        fk_signatures = set()
        for entries in grouped.values():
            entries.sort(key=lambda row: row[1])
            fk_signatures.add((tuple(r[3] for r in entries), entries[0][2], tuple(r[4] for r in entries), entries[0][5], entries[0][6]))
        expected_fks = {(
            tuple(fk["columns"]), fk["references_table"], tuple(fk["references_columns"]),
            fk.get("on_update", "NO ACTION"), fk.get("on_delete", "NO ACTION"),
        ) for fk in table.get("foreign_keys", [])}
        if fk_signatures != expected_fks:
            raise StateError(f"SQLite FK definitions differ from design for {name}")

        indexed = connection.execute(f'PRAGMA index_list("{name}")').fetchall()
        index_map = {idx[1]: idx for idx in indexed}
        for idx in table.get("indexes", []):
            if idx["name"] not in index_map:
                raise StateError(f"SQLite index missing: {idx['name']}")
            columns = [row[2] for row in connection.execute(f'PRAGMA index_info("{idx["name"]}")').fetchall()]
            if columns != idx["columns"]:
                raise StateError(f"SQLite index column mismatch for {idx['name']}")
        actual_unique_sets = {tuple(row[2] for row in connection.execute(f'PRAGMA index_info("{idx[1]}")').fetchall()) for idx in indexed if idx[3] == "u"}
        for unique in table.get("uniques", []):
            if tuple(unique) not in actual_unique_sets:
                raise StateError(f"SQLite unique constraint missing on {name}({', '.join(unique)})")


@contextmanager
def sqlite_connection(database: Path | None = None, *, allow_fk_probe: bool = False):
    if database is not None and database.is_dir():
        raise StateError(f"SQLite database path is a directory: {database}; SQL was not executed.")
    try:
        connection = sqlite3.connect(str(database) if database is not None else ":memory:")
    except sqlite3.Error as exc:
        raise StateError(f"Could not open SQLite database: {exc}; SQL was not executed.") from exc
    try:
        connection.execute("PRAGMA foreign_keys=ON")

        def authorize(action, arg1, arg2, database, trigger):
            # Scripts are generated by an LLM. Do not allow disk attachment,
            # destructive DDL, or disabling foreign-key enforcement during tests.
            if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_DROP_TABLE}:
                return sqlite3.SQLITE_DENY
            read_only = {"foreign_key_check", "table_info", "table_xinfo", "foreign_key_list", "index_list", "index_info"}
            if action == sqlite3.SQLITE_PRAGMA and str(arg1).lower() not in read_only:
                if allow_fk_probe and arg1 == "defer_foreign_keys" and arg2 == "ON":
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        yield connection
    except sqlite3.Error as exc:
        raise StateError(f"SQLite execution failed: {exc}") from exc
    finally:
        connection.close()


def execute_sqlite(schema: str, seed: str, tables: list[str], design: dict[str, Any] | None = None,
                   database: Path | None = None) -> dict[str, int]:
    """Execute and check seed in memory or in a user-selected SQLite file."""
    with sqlite_connection(database) as connection:
        connection.executescript(schema)
        if design is not None:
            _check_sqlite_structure(connection, design)
        connection.executescript(seed)
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        if not all(counts.values()):
            raise StateError(f"empty tables after seeding: {[table for table, count in counts.items() if count == 0]}")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise StateError(f"SQLite foreign-key violations: {violations}")
        return counts
