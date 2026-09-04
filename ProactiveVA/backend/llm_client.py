"""
LiteLLM client for ProactiveVA.

"""
from __future__ import annotations

import json
import os
import time
from typing import Any

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


DEFAULT_BASE_URL = "<your litellm api>"
DEFAULT_PERCEPTION_MODEL = "gemini/ggap/gemini-2.5-flash"
DEFAULT_REASONING_MODEL  = "gemini/ggap/gemini-2.5-flash"
DEFAULT_TIMEOUT_S = 30.0


class LLMUnavailable(RuntimeError):
    """Raised when no API key is configured or the SDK is missing."""


class LLMClient:
    """Thin singleton-ish wrapper around the OpenAI SDK pointed at LiteLLM."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("LITELLM_API_KEY", "").strip()
        self.base_url = os.environ.get("LITELLM_BASE_URL", DEFAULT_BASE_URL).strip()
        self.perception_model = os.environ.get(
            "PROACTIVEVA_PERCEPTION_MODEL", DEFAULT_PERCEPTION_MODEL
        )
        self.reasoning_model = os.environ.get(
            "PROACTIVEVA_REASONING_MODEL", DEFAULT_REASONING_MODEL
        )
        self._client: Any = None
        if _HAS_OPENAI and self.api_key:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.0,
        json_mode: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        messages: list[dict] | None = None,
    ) -> Any:
        """
        Run a single chat completion.

        If `messages` is provided, it overrides the system+user pair

        Returns the raw response object so callers can inspect tool_calls
        """
        if not self.available:
            raise LLMUnavailable(
                "LITELLM_API_KEY is not set. Export it before starting the server."
            )

        if messages is None:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        kwargs: dict[str, Any] = {
            "model": model or self.perception_model,
            "messages": messages,
            "temperature": temperature,
            "timeout": DEFAULT_TIMEOUT_S,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        return self._client.chat.completions.create(**kwargs)

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.0,
        retries: int = 1,
    ) -> dict:
        """
        Convenience wrapper that requests a JSON object and parses the result.

        Falls back to extracting the first {...} block if `response_format`
        is rejected by the upstream model.
        """
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = self.chat(
                    system=system, user=user, model=model,
                    temperature=temperature, json_mode=True,
                )
                content = resp.choices[0].message.content or "{}"
                return _parse_json(content)
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(0.5)
        # final fallback — try once without json_mode
        try:
            resp = self.chat(system=system, user=user, model=model, temperature=temperature)
            content = resp.choices[0].message.content or "{}"
            return _parse_json(content)
        except Exception:
            if last_exc:
                raise last_exc
            raise


def _parse_json(text: str) -> dict:
    """Robust JSON parse — strips markdown fencing and isolates the first object."""
    s = text.strip()
    if s.startswith("```"):
        # ```json ... ``` or ``` ... ```
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(s[start:end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


# Module-level singleton 
_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
