"""Pure validation of agent-generated decisions and the single structured design model."""
from __future__ import annotations

import re
from typing import Any

from .session import SUPPORTED_DBMS, StateError

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def required_text(item: dict, key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StateError(f"{key} must be a nonempty string")
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise StateError(f"unsafe or invalid SQL identifier: {value!r}")
    return value


def validate_dbms_choice(choice: dict[str, Any]) -> None:
    if not isinstance(choice, dict) or choice.get("selected") not in SUPPORTED_DBMS:
        raise StateError(f"DBMS must be one of {SUPPORTED_DBMS}")
    required_text(choice, "rationale")
    comparisons = choice.get("comparison")
    if not isinstance(comparisons, list) or len(comparisons) != len(SUPPORTED_DBMS):
        raise StateError("comparison must have one row for each supported DBMS")
    if {row.get("dbms") for row in comparisons if isinstance(row, dict)} != set(SUPPORTED_DBMS):
        raise StateError("comparison must cover all supported DBMSs")
    for row in comparisons:
        required_text(row, "advantages")
        required_text(row, "tradeoffs")
        required_text(row, "fit")
    rejected = choice.get("rejected")
    if not isinstance(rejected, dict) or set(rejected) != set(SUPPORTED_DBMS) - {choice["selected"]}:
        raise StateError("explain rejection of every nonselected DBMS")
    for value in rejected.values():
        if not isinstance(value, str) or not value.strip():
            raise StateError("rejected DBMS reasons cannot be empty")


def validate_design(model: dict[str, Any]) -> None:
    if not isinstance(model, dict):
        raise StateError("design model must be an object")
    tables = model.get("tables")
    if not isinstance(tables, list) or not tables:
        raise StateError("design must contain tables")
    names: set[str] = set()
    names_normalized: set[str] = set()
    index_names: set[str] = set()
    columns_by_table: dict[str, set[str]] = {}
    for table in tables:
        if not isinstance(table, dict):
            raise StateError("table must be an object")
        name = identifier(table.get("name"))
        required_text(table, "description")
        if name.casefold() in names_normalized:
            raise StateError(f"duplicate table: {name}")
        names.add(name)
        names_normalized.add(name.casefold())
        columns = table.get("columns")
        if not isinstance(columns, list) or not columns:
            raise StateError(f"{name} must have columns")
        col_names: set[str] = set()
        for column in columns:
            if not isinstance(column, dict):
                raise StateError(f"invalid column in {name}")
            col_name = identifier(column.get("name"))
            required_text(column, "type")
            if not isinstance(column.get("nullable"), bool):
                raise StateError(f"nullable must be boolean in {name}.{col_name}")
            if col_name.casefold() in {existing.casefold() for existing in col_names}:
                raise StateError(f"duplicate column: {name}.{col_name}")
            col_names.add(col_name)
        columns_by_table[name] = col_names
        primary_key = table.get("primary_key")
        if not isinstance(primary_key, list) or not primary_key or not set(primary_key) <= col_names:
            raise StateError(f"missing or invalid primary key in {name}")
        if len(set(primary_key)) != len(primary_key):
            raise StateError(f"duplicate primary-key column in {name}")
        for key in primary_key:
            for col in columns:
                if col["name"] == key and col["nullable"]:
                    raise StateError(f"primary key cannot be nullable: {name}.{key}")
        for unique in table.get("uniques", []):
            if not isinstance(unique, list) or not unique or not set(unique) <= col_names:
                raise StateError(f"invalid unique constraint on {name}")
        for idx in table.get("indexes", []):
            index_name = identifier(idx.get("name"))
            if index_name.casefold() in index_names:
                raise StateError(f"duplicate index name: {index_name}")
            index_names.add(index_name.casefold())
            if not isinstance(idx.get("columns"), list) or not idx["columns"] or not set(idx["columns"]) <= col_names:
                raise StateError(f"invalid index on {name}")
        for check in table.get("checks", []):
            if not isinstance(check, str) or not check.strip():
                raise StateError(f"invalid check expression on {name}")
    for table in tables:
        local_columns = columns_by_table[table["name"]]
        for fk in table.get("foreign_keys", []):
            local, target, remote = fk.get("columns"), fk.get("references_table"), fk.get("references_columns")
            if not isinstance(local, list) or not local or not set(local) <= local_columns:
                raise StateError(f"bad foreign-key columns in {table['name']}")
            if target not in names or not isinstance(remote, list) or len(local) != len(remote) or not set(remote) <= columns_by_table[target]:
                raise StateError(f"bad foreign-key reference in {table['name']}")
            referenced = next(t for t in tables if t["name"] == target)
            if remote != referenced["primary_key"] and remote not in referenced.get("uniques", []):
                raise StateError(f"foreign key must reference a PK or UNIQUE key in {target}")
            if any(fk.get(action) == "SET NULL" for action in ("on_delete", "on_update")):
                local_col_map = {c["name"]: c for c in table["columns"]}
                if any(not local_col_map[col]["nullable"] for col in local):
                    raise StateError("SET NULL requires nullable foreign-key columns")
            for action in ("on_delete", "on_update"):
                if fk.get(action, "NO ACTION") not in {"CASCADE", "RESTRICT", "NO ACTION", "SET NULL", "SET DEFAULT"}:
                    raise StateError(f"invalid {action} action")
    relationships = model.get("relationships")
    if not isinstance(relationships, list):
        raise StateError("relationships must be a list")
    for relation in relationships:
        if relation.get("from") not in names or relation.get("to") not in names:
            raise StateError("relationship references a missing table")
        required_text(relation, "cardinality")
        required_text(relation, "description")
    norms = model.get("normalization")
    if not isinstance(norms, list) or {entry.get("table") for entry in norms} != names:
        raise StateError("normalization entry required for every table")
    for entry in norms:
        required_text(entry, "normal_form")
        required_text(entry, "justification")
        if entry.get("normal_form") not in {"1NF", "2NF", "3NF", "BCNF", "4NF", "5NF", "DENORMALIZED"}:
            raise StateError("unknown normal form")
        if entry["normal_form"] in {"1NF", "2NF", "DENORMALIZED"}:
            required_text(entry, "denormalization_reason")
    for list_name in ("functional_dependencies", "assumptions", "ambiguities", "business_rules"):
        if not isinstance(model.get(list_name), list):
            raise StateError(f"{list_name} must be a list")
    for dependency in model["functional_dependencies"]:
        name = dependency.get("table")
        if name not in names or not set(dependency.get("determinant", [])) <= columns_by_table[name] or not set(dependency.get("dependents", [])) <= columns_by_table[name]:
            raise StateError("invalid functional dependency")
        if not dependency.get("determinant") or not dependency.get("dependents"):
            raise StateError("empty functional dependency")
    for rule in model["business_rules"]:
        required_text(rule, "rule")
        required_text(rule, "implementation")
