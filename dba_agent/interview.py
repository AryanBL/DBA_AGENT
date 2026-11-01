"""Requirements interview validation and artifact rendering.

The interview is recorded on :class:`Session`; this module keeps the stage's
validation and Markdown output deterministic and independent of an LLM provider.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


REQUIRED_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("entities", "Entities and attributes"),
    ("relationships", "Relationships and cardinalities"),
    ("volume", "Data volume and growth"),
    ("workload", "Read/write patterns and reporting"),
    ("transactions", "Transactions, consistency, and concurrency"),
    ("security", "Security, roles, and privacy"),
    ("business_rules", "Business rules and constraints"),
)


def validate_requirements(requirements: Mapping[str, Any]) -> None:
    """Validate that every mandatory interview category has a substantive answer.

    A category may contain an explicit unresolved item, represented by a
    non-empty string or collection.  Empty values are rejected because they
    cannot support DBMS selection.
    """

    missing = [key for key, _ in REQUIRED_CATEGORIES if key not in requirements]
    if missing:
        raise ValueError(f"missing interview categories: {missing}")
    empty = [key for key, _ in REQUIRED_CATEGORIES if not _has_content(requirements[key])]
    if empty:
        raise ValueError(f"empty interview categories: {empty}")


def render_requirements_markdown(
    requirements: Mapping[str, Any], rounds: Iterable[Mapping[str, Any]] = (),
) -> str:
    """Render the accepted interview output as ``requirements.md`` content."""

    validate_requirements(requirements)
    lines = ["# Requirements", "", "Generated from the completed requirements interview.", ""]
    for key, title in REQUIRED_CATEGORIES:
        lines.extend([f"## {title}", "", _format_value(requirements[key]), ""])

    round_list = list(rounds)
    lines.extend(["## Interview rounds", ""])
    if not round_list:
        lines.append("No interview rounds recorded.")
    else:
        for index, round_data in enumerate(round_list, 1):
            lines.extend([f"### Round {index}", ""])
            answers = round_data.get("answers", {})
            if isinstance(answers, Mapping) and answers:
                for question, answer in answers.items():
                    lines.append(f"- **{question}**: {answer}")
            else:
                lines.append("- No answers recorded.")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _has_content(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return bool(value)
    return True


def _format_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return "\n".join(f"- **{key}**: {item}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return "\n".join(f"- {item}" for item in value)
    return str(value)
