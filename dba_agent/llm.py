"""OpenAI-compatible chat adapter, external prompts, JSON parsing and per-attempt logs."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Config


class LLMError(RuntimeError):
    pass


def parse_json(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model did not return valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("model response must be one JSON object")
    return parsed


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")


class LLMClient:
    """`transport` injection allows fully offline tests without monkeypatching HTTP."""

    def __init__(self, config: Config, transport: Callable[[str, str, dict[str, Any], int], str] | None = None):
        self.config = config
        self.transport = transport or self._http
        self.log_path = config.output_dir / "llm-calls.jsonl"

    def _http(self, url: str, api_key: str, body: dict[str, Any], timeout: int) -> str:
        if not api_key:
            raise LLMError("set DBA_AGENT_API_KEY to use a hosted OpenAI-compatible model")
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TypeError) as exc:
            raise LLMError(f"model call failed: {exc}") from exc

    def ask(self, stage: str, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        prompt_path = self.config.prompt_dir / f"{prompt}.txt"
        instructions = prompt_path.read_text(encoding="utf-8")
        body = {
            "model": self.config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        last_error = ""
        for attempt in range(1, self.config.llm_attempts + 1):
            raw: str | None = None
            error: str | None = None
            try:
                raw = self.transport(url, self.config.api_key, body, self.config.timeout)
                return_value = parse_json(raw)
                return return_value
            except (LLMError, ValueError, TypeError) as exc:
                error, last_error = str(exc), str(exc)
            finally:
                append_jsonl(self.log_path, {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "stage": stage,
                    "prompt": prompt,
                    "attempt": attempt,
                    "model": self.config.model,
                    "input": payload,
                    "output": raw,
                    "error": error,
                })
        raise LLMError(f"{stage} failed after {self.config.llm_attempts} attempt(s): {last_error}")
