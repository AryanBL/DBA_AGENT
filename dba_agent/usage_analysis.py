"""Summarize recorded token consumption by app, session, stage and second."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


FIELDS = ("calls", "cache_hits", "estimated_calls", "input_tokens", "output_tokens", "total_tokens")


def analyze(path: Path) -> dict:
    app = defaultdict(int)
    sessions = defaultdict(lambda: defaultdict(int))
    stages = defaultdict(lambda: defaultdict(int))
    seconds = defaultdict(lambda: defaultdict(int))
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                usage = record.get("accounting", {})
                second = record["timestamp"][:19] + "Z"
                for bucket in (app, sessions[record.get("session_id") or "unassigned"],
                               stages[record.get("stage") or "unknown"], seconds[second]):
                    for field in FIELDS:
                        bucket[field] += usage.get(field, 0)
    return {"app": dict(app), "sessions": {k: dict(v) for k, v in sorted(sessions.items())},
            "stages": {k: dict(v) for k, v in sorted(stages.items())},
            "seconds": {k: dict(v) for k, v in sorted(seconds.items())}}
