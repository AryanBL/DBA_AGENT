"""Runtime settings read from environment; no source editing is needed to switch providers."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding real environment variables."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name or name in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[name] = value


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Config:
    base_url: str = "https://api.gapgpt.app/v1"
    model: str = "gapgpt-deepseek-v4.1-flash"
    api_key: str = field(default="", repr=False)
    state_dir: Path = Path(".dba_agent/sessions")
    output_dir: Path = Path("output")
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"
    timeout: int = 60
    llm_attempts: int = 2
    max_interview_rounds: int = 6
    max_sql_attempts: int = 3
    cache_enabled: bool = True

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
            # Keep the project-specific name authoritative, while accepting the
            # name used in Kilo's own documentation as a convenient fallback.
            api_key=os.getenv("DBA_AGENT_API_KEY", os.getenv("KILO_API_KEY", "")),
            state_dir=Path(os.getenv("DBA_AGENT_STATE_DIR", ".dba_agent/sessions")),
            output_dir=Path(os.getenv("DBA_AGENT_OUTPUT_DIR", "output")),
            prompt_dir=Path(os.getenv("DBA_AGENT_PROMPT_DIR", str(Path(__file__).resolve().parent / "prompts"))),
            timeout=number("DBA_AGENT_TIMEOUT", 60),
            llm_attempts=number("DBA_AGENT_LLM_ATTEMPTS", 2),
            max_interview_rounds=number("DBA_AGENT_MAX_INTERVIEW_ROUNDS", 6),
            max_sql_attempts=number("DBA_AGENT_MAX_SQL_ATTEMPTS", 3),
            cache_enabled=os.getenv("DBA_AGENT_CACHE_ENABLED", "1").lower() not in {"0", "false", "no"},
        )
