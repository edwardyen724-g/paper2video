from __future__ import annotations
import json
import os
import time
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str, system: str | None = None) -> str: ...
    def complete_json(self, prompt: str, system: str | None = None) -> dict: ...


class FakeLLMClient:
    """Test double. Returns queued responses in order."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        if not self._responses:
            raise RuntimeError("FakeLLMClient ran out of responses")
        return self._responses.pop(0)

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        raw = self.complete(prompt, system)
        return json.loads(raw)


class AnthropicClient:
    """Production LLM client backed by Anthropic API."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        import anthropic  # lazy
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model or os.environ.get("PAPER2VIDEO_MODEL", "claude-sonnet-4-6")

    def complete(self, prompt: str, system: str | None = None) -> str:
        import anthropic  # lazy
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        # Retry transient errors (connection, timeout, 5xx, 529 overloaded).
        # Capped backoff so we don't burn 20 minutes on a single scene.
        retryable = (
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.InternalServerError,
        )
        backoff_schedule = [3, 8, 20, 45, 90]  # ~166s total, then raise
        last_exc: Exception | None = None
        for attempt, wait in enumerate([*backoff_schedule, None]):
            try:
                msg = self._client.messages.create(**kwargs)
                return msg.content[0].text
            except retryable as e:
                last_exc = e
            except anthropic.APIStatusError as e:
                if e.status_code not in (429, 502, 503, 504, 529):
                    raise
                last_exc = e
            if wait is None:
                break
            time.sleep(wait)
        assert last_exc is not None
        raise last_exc

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        sys_prompt = (system or "") + "\n\nRespond with valid JSON only. No prose, no code fences."
        raw = self.complete(prompt, sys_prompt.strip())
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
        return json.loads(raw)
