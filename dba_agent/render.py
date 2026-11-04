"""Deterministic Markdown renderers; always derive documentation from structured state."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .session import Session


def write_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("`", "'")


def choice_markdown(choice: dict[str, Any]) -> str:
    lines = ["# DBMS Selection", "", f"**Selected:** {choice['selected']}", "", "## Decision rationale", "", choice["rationale"], "", "## Comparison", "", "| DBMS | Advantages | Tradeoffs | Fit |", "|---|---|---|---|"]
    for row in choice["comparison"]:
        lines.append("| " + " | ".join(md(row[k]) for k in ("dbms", "advantages", "tradeoffs", "fit")) + " |")
    lines.extend(["", "## Alternatives rejected", ""])
    for dbms, reason in choice["rejected"].items():
        lines.append(f"- **{dbms}:** {reason}")
    return "\n".join(lines) + "\n"


def diagram(model: dict[str, Any]) -> str:
    lines = ["```mermaid", "erDiagram"]
    for table in model["tables"]:
        lines.append(f"    {table['name']} {{")
        for col in table["columns"]:
            # Mermaid attributes are intentionally identifier-safe. Types can contain parentheses/spaces.
            safe_type = "".join(c if c.isalnum() or c == "_" else "_" for c in col["type"])
            tag = " PK" if col["name"] in table["primary_key"] else ""
            lines.append(f"        {safe_type} {col['name']}{tag}")
        lines.append("    }")
    for table in model["tables"]:
        for fk in table.get("foreign_keys", []):
            target = fk["references_table"]
            lines.append(f"    {target} ||--o{{ {table['name']} : references")
    lines.append("```")
    return "\n".join(lines)


def conceptual_markdown(model: dict[str, Any]) -> str:
    lines = ["# Conceptual Model", "", "## Entities", ""]
    for table in model["tables"]:
        lines.append(f"- **{table['name']}** - {table['description']}")
    lines.extend(["", "## Relationships and cardinalities", ""])
    for r in model["relationships"]:
        lines.append(f"- **{r['from']} -> {r['to']}** ({r['cardinality']}): {r['description']}")
    if not model["relationships"]:
        lines.append("No conceptual relationships specified.")
    lines.extend(["", "## ER diagram", "", diagram(model)])
    return "\n".join(lines) + "\n"


def logical_markdown(model: dict[str, Any], dbms: str) -> str:
    lines = ["# Logical Schema", "", f"**Target DBMS:** {dbms}", ""]
    for table in model["tables"]:
        lines.extend([f"## {table['name']}", "", table["description"], "", "| Column | Type | Nullable |", "|---|---|---|"])
        for col in table["columns"]:
            lines.append(f"| `{col['name']}` | `{md(col['type'])}` | {'Yes' if col['nullable'] else 'No'} |")
        lines.extend(["", f"- **Primary key:** {', '.join(table['primary_key'])}"])
        for unique in table.get("uniques", []):
            lines.append(f"- **Unique:** {', '.join(unique)}")
        for fk in table.get("foreign_keys", []):
            lines.append(f"- **Foreign key:** ({', '.join(fk['columns'])}) -> {fk['references_table']}({', '.join(fk['references_columns'])}); ON DELETE {fk.get('on_delete', 'NO ACTION')}; ON UPDATE {fk.get('on_update', 'NO ACTION')}")
        for check in table.get("checks", []):
            lines.append(f"- **Check:** `{check}`")
        for idx in table.get("indexes", []):
            lines.append(f"- **Index:** {idx['name']} ({', '.join(idx['columns'])})")
        lines.append("")
    lines.extend(["## Relational schema diagram", "", diagram(model)])
    return "\n".join(lines) + "\n"


def normalization_markdown(model: dict[str, Any]) -> str:
    lines = ["# Normalization Analysis", "", "## Functional dependencies", ""]
    for fd in model["functional_dependencies"]:
        lines.append(f"- **{fd['table']}:** {', '.join(fd['determinant'])} -> {', '.join(fd['dependents'])}")
    if not model["functional_dependencies"]:
        lines.append("No explicit functional dependencies were supplied; this requires manual review.")
    lines.extend(["", "## Normal forms and denormalization", "", "| Table | Normal form | Justification | Denormalization reason |", "|---|---|---|---|"])
    for norm in model["normalization"]:
        lines.append("| " + " | ".join(md(norm.get(key, "")) for key in ("table", "normal_form", "justification", "denormalization_reason")) + " |")
    return "\n".join(lines) + "\n"


def assumptions_markdown(model: dict[str, Any]) -> str:
    lines = ["# Assumptions and Open Questions", "", "## Assumptions", ""]
    lines += [f"- {item}" for item in model["assumptions"]] or ["- None recorded."]
    lines.extend(["", "## Unresolved ambiguities", ""])
    lines += [f"- {item}" for item in model["ambiguities"]] or ["- None recorded."]
    lines.extend(["", "## Business-rule traceability", "", "| Rule | Implementation |", "|---|---|"])
    lines += [f"| {md(r['rule'])} | {md(r['implementation'])} |" for r in model["business_rules"]]
    return "\n".join(lines) + "\n"


def changelog_markdown(history: list[dict[str, Any]]) -> str:
    lines = ["# Change Log", ""]
    if not history:
        lines.append("No revisions yet.")
    for event in history:
        lines.extend([f"## Version {event['from']} -> {event['to']} ({event['timestamp']})", "", f"**User request:** {event['request']}", "", f"**Reason/interpretation:** {event['reason']}", "", f"**Regenerated files:** {', '.join(event['affected_files'])}", "", "**SQL status:** Invalidated; regenerate only after fresh approval.", ""])
    return "\n".join(lines) + "\n"


def render_session(session: Session, root: Path) -> dict[str, str]:
    """Writes all non-SQL artifacts into version-specific output, avoiding stale files."""
    version_dir = root / session.session_id / f"v{session.active_version}"
    model = session.design.model
    files = {
        "requirements.md": session.requirements_markdown(),
        "dbms-choice.md": choice_markdown(session.dbms_choice),
        "conceptual-model.md": conceptual_markdown(model),
        "logical-schema.md": logical_markdown(model, session.dbms_choice["selected"]),
        "normalization.md": normalization_markdown(model),
        "assumptions.md": assumptions_markdown(model),
    }
    for name, content in files.items():
        write_file(version_dir / name, content)
        session.design.artifacts[name] = str(version_dir / name)
    write_file(root / session.session_id / "changelog.md", changelog_markdown(session.revision_history))
    return {key: str(version_dir / key) for key in files}
