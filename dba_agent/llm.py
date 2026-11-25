"""OpenAI-compatible chat adapter, external prompts, JSON parsing and per-attempt logs."""
from __future__ import annotations

import json
import hashlib
import math
from copy import deepcopy
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Config


class LLMError(RuntimeError):
    pass


class NetworkError(LLMError):
    pass


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def estimated_tokens(value: str) -> int:
    """Tokenizer-independent approximation, not a billing count."""
    return math.ceil(len(value.encode("utf-8")) / 4)


def parse_json(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise LLMError("model response content must be text")
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
        self.cache: dict[str, dict[str, Any]] = {}
        self.records: list[dict[str, Any]] = []
        self.totals: dict[str, int] = {}
        self.session_totals: dict[str, dict[str, int]] = {}
        self._provider_usage: dict[str, Any] = {}

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(self.config.api_key, "[REDACTED]") if self.config.api_key else value
        if isinstance(value, dict):
            return {self.redact(k): self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value

    def _http(self, url: str, api_key: str, body: dict[str, Any], timeout: int) -> str:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        # Kilo permits anonymous requests to eligible free models. Other
        # providers may also support unauthenticated local/public endpoints.
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise LLMError("provider response must be an object")
            self._provider_usage = payload.get("usage") or {}
            return payload["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise NetworkError(self.redact(f"model call failed: {exc}")) from None
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise LLMError(self.redact(f"invalid provider response: {exc}")) from None

    def ask(self, stage: str, prompt: str, payload: dict[str, Any], *,
            session_id: str | None = None, validator: Callable | None = None,
            cache_context: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt_path = self.config.prompt_dir / f"{prompt}.txt"
        instructions = prompt_path.read_text(encoding="utf-8")
        body = {
            "model": self.config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": compact_json(payload)},
            ],
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        fingerprint = hashlib.sha256(compact_json({"url": url, "body": body, "stage": stage,
            "prompt": prompt, "context": cache_context,
            "auth": hashlib.sha256(self.config.api_key.encode()).hexdigest()}).encode()).hexdigest()
        last_error = ""
        validation_error = None
        for attempt in range(1, self.config.llm_attempts + 1):
            sent_body = compact_json(body)
            raw: str | None = None
            error: str | None = None
            error_kind = None
            cached = self.config.cache_enabled and fingerprint in self.cache
            self._provider_usage = {}
            try:
                if cached:
                    raw = compact_json(self.cache[fingerprint])
                else:
                    response = self.transport(url, self.config.api_key, body, self.config.timeout)
                    if isinstance(response, dict):
                        self._provider_usage = response.get("usage") or {}
                        raw = response["choices"][0]["message"]["content"]
                    else:
                        raw = response
                return_value = parse_json(raw)
                error_kind = "validation"
                if validator:
                    validator(return_value)
                if self.config.cache_enabled:
                    self.cache[fingerprint] = deepcopy(return_value)
                return return_value
            except (LLMError, ValueError, TypeError, KeyError, IndexError, TimeoutError, OSError) as exc:
                error_kind = "network" if isinstance(exc, (NetworkError, TimeoutError, OSError)) else error_kind or "invalid_json"
                error = last_error = self.redact(str(exc))
                if error_kind == "validation":
                    validation_error = exc
                self.cache.pop(fingerprint, None)
                # Only JSON/validation repair needs corrective context. Network retries reuse the exact body.
                if error_kind != "network":
                    body["messages"] = body["messages"][:2] + [{"role": "user", "content":
                        "Correct the previous response. Return valid JSON satisfying the schema. Error: " + error}]
            finally:
                usage = self._provider_usage if isinstance(self._provider_usage, dict) else {}
                input_count = usage.get("prompt_tokens", usage.get("input_tokens"))
                output_count = usage.get("completion_tokens", usage.get("output_tokens"))
                input_reported = type(input_count) is int and input_count >= 0
                output_reported = type(output_count) is int and output_count >= 0
                reported = input_reported and output_reported
                accounting = {"calls": 1, "cache_hits": int(cached),
                    "input_tokens": 0 if cached else input_count if input_reported else estimated_tokens(sent_body),
                    "output_tokens": 0 if cached else output_count if output_reported else estimated_tokens(raw or ""),
                    "estimated_calls": int(not reported and not cached)}
                accounting["total_tokens"] = accounting["input_tokens"] + accounting["output_tokens"]
                for totals in (self.totals, self.session_totals.setdefault(session_id or "unassigned", {})):
                    for key, count in accounting.items():
                        totals[key] = totals.get(key, 0) + count
                record = self.redact({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "stage": stage,
                    "prompt": prompt,
                    "attempt": attempt,
                    "model": self.config.model,
                    "input": payload,
                    "output": raw,
                    "error": error,
                    "error_kind": error_kind if error else None,
                    "session_id": session_id,
                    "usage": usage,
                    "accounting": accounting,
                    "usage_source": "cache" if cached else "provider" if reported else "estimated" if not input_reported and not output_reported else "mixed",
                    "input_hash": fingerprint,
                })
                self.records.append(record)
                append_jsonl(self.log_path, record)
        if validation_error is not None:
            raise type(validation_error)(self.redact(str(validation_error))) from None
        raise LLMError(f"{stage} failed after {self.config.llm_attempts} attempt(s): {last_error}")
