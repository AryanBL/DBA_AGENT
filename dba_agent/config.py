"""Runtime settings read from environment; no source editing is needed to switch providers."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    state_dir: Path = Path(".dba_agent/sessions")
    output_dir: Path = Path("output")
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"
    timeout: int = 60
    llm_attempts: int = 2
    max_interview_rounds: int = 6
    max_sql_attempts: int = 3

    @classmethod
    def from_env(cls) -> "Config":
        def number(name: str, default: int) -> int:
            result = int(os.getenv(name, str(default)))
            if result < 1:
                raise ValueError(f"{name} must be >= 1")
            return result
        return cls(
            base_url=os.getenv("DBA_AGENT_BASE_URL", cls.base_url),
            model=os.getenv("DBA_AGENT_MODEL", cls.model),
            api_key=os.getenv("DBA_AGENT_API_KEY", ""),
            state_dir=Path(os.getenv("DBA_AGENT_STATE_DIR", ".dba_agent/sessions")),
            output_dir=Path(os.getenv("DBA_AGENT_OUTPUT_DIR", "output")),
            prompt_dir=Path(os.getenv("DBA_AGENT_PROMPT_DIR", str(Path(__file__).resolve().parent / "prompts"))),
            timeout=number("DBA_AGENT_TIMEOUT", 60),
            llm_attempts=number("DBA_AGENT_LLM_ATTEMPTS", 2),
            max_interview_rounds=number("DBA_AGENT_MAX_INTERVIEW_ROUNDS", 6),
            max_sql_attempts=number("DBA_AGENT_MAX_SQL_ATTEMPTS", 3),
        )
