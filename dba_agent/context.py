"""Deterministic, lossless deduplication of workflow context."""
from __future__ import annotations

import re
from typing import Any

from .session import Session


def interview_summary(session: Session) -> dict[str, Any]:
    assessment = session.interview_assessment or session.metadata.get("last_assessment", {})
    facts: list[str] = []
    fact_ids: dict[str, int] = {}

    def intern(text: str) -> list[int]:
        ids = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line not in fact_ids:
                fact_ids[line] = len(facts)
                facts.append(line)
            ids.append(fact_ids[line])
        return ids

    questions = []
    recent = []
    answer_facts = []
    for index, round_ in enumerate(session.interview_rounds):
        for question in round_["questions"]:
            if question not in questions:
                questions.append(question)
            ids = intern(round_["answers"][question])
            answer_facts.append({"question": questions.index(question), "fact_ids": ids})
            if index == len(session.interview_rounds) - 1:
                recent.append({"question": questions.index(question), "fact_ids": ids})
    return {"established_facts": facts, "intake": session.intake_summary,
        "covered_categories": [key for key, value in assessment.get("coverage", {}).items() if value],
        "unresolved_topics": assessment.get("missing_topics", []),
        "contradictions": assessment.get("critical_contradictions", []),
        "answer_facts": answer_facts,
        "recent_answers": recent, "previously_asked_questions": questions,
        "round_count": len(session.interview_rounds)}


def sql_design(model: dict[str, Any]) -> dict[str, Any]:
    return {key: model[key] for key in ("tables", "business_rules", "assumptions", "ambiguities") if key in model}


def repair_context(schema: str, seed: str, model: dict[str, Any], error: str, dbms: str) -> dict[str, Any]:
    index_match = re.fullmatch(r"SQLite index missing: ([A-Za-z_][A-Za-z_0-9]*)", error)
    if index_match:
        for table in model["tables"]:
            for index in table.get("indexes", []):
                if index["name"] == index_match[1]:
                    return {"dbms": dbms, "mode": "append_schema", "table": table,
                            "index": index, "validation_error": error}
    # Localize only simple missing-seed coverage errors. Arbitrary SQL, triggers,
    # syntax and FK errors require the full scripts to avoid unsafe SQL splitting.
    match = re.fullmatch(r"seed.sql does not populate ([A-Za-z_][A-Za-z_0-9]*)", error)
    if match:
        table = next((t for t in model["tables"] if t["name"] == match[1]), None)
        if table is not None and not table.get("foreign_keys"):
            return {"dbms": dbms, "mode": "append_seed", "table": table,
                    "validation_error": error}
    return {"dbms": dbms, "design": model, "previous_schema": schema,
            "previous_seed": seed, "validation_error": error}
