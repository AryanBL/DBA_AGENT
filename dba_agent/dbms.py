"""DBMS selection validation and Markdown rendering.

The selector keeps the decision record structured so later design and SQL
stages can use one authoritative choice instead of parsing Markdown.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SUPPORTED_DBMS: tuple[str, ...] = (
    "PostgreSQL",
    "MySQL/MariaDB",
    "SQLite",
    "SQL Server",
)

REQUIREMENT_CATEGORIES: tuple[str, ...] = (
    "entities",
    "relationships",
    "volume",
    "workload",
    "transactions",
    "security",
    "business_rules",
)


def validate_dbms_choice(choice: Mapping[str, Any]) -> None:
    """Validate a completed DBMS recommendation.

    The comparison and evidence fields are intentionally required here. They
    make the decision auditable and give the design stage enough context to
    explain why the selected engine fits the interview results.
    """

    if not isinstance(choice, Mapping):
        raise ValueError("DBMS choice must be an object")

    selected = choice.get("selected")
    if selected not in SUPPORTED_DBMS:
        raise ValueError(f"selected DBMS must be one of {list(SUPPORTED_DBMS)}")

    _require_text(choice, "rationale")

    comparison = choice.get("comparison")
    if not isinstance(comparison, Mapping):
        raise ValueError("comparison must be an object")
    missing = [dbms for dbms in SUPPORTED_DBMS if dbms not in comparison]
    if missing:
        raise ValueError(f"comparison is missing DBMS entries: {missing}")
    for dbms in SUPPORTED_DBMS:
        _validate_comparison_entry(dbms, comparison[dbms])

    rejected = choice.get("rejected")
    if not isinstance(rejected, Mapping):
        raise ValueError("rejected must be an object")
    missing_rejections = [dbms for dbms in SUPPORTED_DBMS if dbms != selected and dbms not in rejected]
    if missing_rejections:
        raise ValueError(f"rejected is missing reasons for: {missing_rejections}")
    for dbms, reason in rejected.items():
        if dbms not in SUPPORTED_DBMS or dbms == selected:
            raise ValueError(f"rejected contains invalid DBMS: {dbms}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"rejection reason for {dbms} must be non-empty")

    evidence = choice.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence must be an object")
    missing_evidence = [category for category in REQUIREMENT_CATEGORIES if category not in evidence]
    if missing_evidence:
        raise ValueError(f"evidence is missing requirement categories: {missing_evidence}")
    for category, explanation in evidence.items():
        if category not in REQUIREMENT_CATEGORIES:
            raise ValueError(f"evidence contains an unknown requirement category: {category}")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError(f"evidence for {category} must be non-empty")


def render_dbms_choice_markdown(choice: Mapping[str, Any]) -> str:
    """Render a validated DBMS recommendation as ``dbms-choice.md``."""

    validate_dbms_choice(choice)
    selected = choice["selected"]
    comparison = choice["comparison"]
    rejected = choice["rejected"]
    evidence = choice["evidence"]

    lines = [
        "# DBMS Selection",
        "",
        f"## Selected DBMS\n\n**{selected}**",
        "",
        "## Decision rationale",
        "",
        str(choice["rationale"]),
        "",
        "## Requirements evidence",
        "",
    ]
    for category in REQUIREMENT_CATEGORIES:
        lines.extend([f"### {category.replace('_', ' ').title()}", "", str(evidence[category]), ""])

    lines.extend([
        "## Comparison",
        "",
        "| DBMS | Strengths | Limitations | Fit assessment |",
        "| --- | --- | --- | --- |",
    ])
    for dbms in SUPPORTED_DBMS:
        entry = comparison[dbms]
        lines.append(
            f"| {dbms} | {_cell(entry['strengths'])} | "
            f"{_cell(entry['limitations'])} | {_cell(entry['fit'])} |"
        )

    lines.extend(["", "## Rejected alternatives", ""])
    for dbms in SUPPORTED_DBMS:
        if dbms != selected:
            lines.extend([f"### {dbms}", "", str(rejected[dbms]), ""])
    return "\n".join(lines).rstrip() + "\n"


def _require_text(value: Mapping[str, Any], key: str) -> None:
    if not isinstance(value.get(key), str) or not value[key].strip():
        raise ValueError(f"{key} must be a non-empty string")


def _validate_comparison_entry(dbms: str, entry: Any) -> None:
    if not isinstance(entry, Mapping):
        raise ValueError(f"comparison entry for {dbms} must be an object")
    for key in ("strengths", "limitations", "fit"):
        value = entry.get(key)
        if isinstance(value, str):
            if not value.strip():
                raise ValueError(f"comparison {key} for {dbms} must be non-empty")
        elif isinstance(value, (list, tuple)):
            if not value or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"comparison {key} for {dbms} must contain text")
        else:
            raise ValueError(f"comparison {key} for {dbms} must contain text")


def _cell(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(item) for item in value)
    return str(value).replace("|", "\\|").replace("\n", " ")
