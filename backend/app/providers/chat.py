"""OpenAI and Groq providers via their official SDKs' chat.completions API.

Capability differences are explicit:
- OpenAI: strict json_schema on current models; no temperature param sent
  (reasoning models reject non-default values).
- Groq: strict json_schema only on the models in GROQ_STRICT_MODELS (per
  console.groq.com/docs/structured-outputs); other models fall back to
  json_object mode with the schema in the prompt, and Pydantic validates.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

import groq
import openai

from app.providers.base import (
    LLMResult,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderQuotaExhausted,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    with_retries,
)

GROQ_STRICT_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "meta-models/muse-spark-open"}


def _map_error(provider: str, sdk: Any, e: Exception) -> ProviderError:
    if isinstance(e, sdk.APITimeoutError):
        return ProviderTimeout(provider, "request timed out")
    if isinstance(e, sdk.RateLimitError):
        body = getattr(e, "body", None)
        code = (body or {}).get("code") if isinstance(body, dict) else None
        if code in ("insufficient_quota", "credit_balance_exhausted") or "insufficient_quota" in str(e):
            return ProviderQuotaExhausted(provider, "account quota/credits exhausted; add credits or switch provider")
        retry_after = None
        headers = getattr(getattr(e, "response", None), "headers", None) or {}
        with contextlib.suppress(TypeError, ValueError):
            ra = headers.get("retry-after")
            retry_after = float(ra) if ra else None
        return ProviderRateLimited(provider, "rate limited (429)", retry_after=retry_after)
    if isinstance(e, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
        return ProviderAuthError(provider, "authentication failed; check API key")
    if isinstance(e, sdk.APIConnectionError):
        return ProviderUnavailable(provider, "connection error")
    if isinstance(e, sdk.APIStatusError):
        if e.status_code >= 500:
            return ProviderUnavailable(provider, f"server error {e.status_code}")
        # e.g. Groq best-effort schema 400 "Generated JSON does not match the expected schema"
        return ProviderBadResponse(provider, f"HTTP {e.status_code}: {str(e)[:200]}")
    return ProviderError(provider, f"unexpected error: {type(e).__name__}")


class ChatCompletionsProvider:
    supports_narrative = True

    def __init__(self, name: str, client: Any, sdk: Any, model: str, *, strict: bool, max_retries: int,
                 send_temperature: bool):
        self.name, self.client, self.sdk, self.model = name, client, sdk, model
        self.strict, self.max_retries, self.send_temperature = strict, max_retries, send_temperature

    def _call(self, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> LLMResult:
        if self.strict:
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        else:
            response_format = {"type": "json_object"}
            system = f"{system}\n\nReturn only a JSON object matching this JSON Schema:\n{json.dumps(schema)}"
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=response_format,
        )
        if self.send_temperature:
            kwargs["temperature"] = 0
        t0 = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as e:  # SDK exceptions mapped to typed errors
            raise _map_error(self.name, self.sdk, e) from e
        latency = (time.perf_counter() - t0) * 1000
        choice = resp.choices[0]
        content = choice.message.content or ""
        if getattr(choice, "finish_reason", None) == "length":
            raise ProviderBadResponse(self.name, "output truncated (finish_reason=length)")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ProviderBadResponse(self.name, f"invalid JSON: {e}") from e
        if not isinstance(data, dict):
            raise ProviderBadResponse(self.name, "JSON root is not an object")
        usage = getattr(resp, "usage", None)
        return LLMResult(
            data=data, provider=self.name, model=self.model, latency_ms=latency,
            input_tokens=getattr(usage, "prompt_tokens", None), output_tokens=getattr(usage, "completion_tokens", None),
            structured_mode="json_schema_strict" if self.strict else "json_object",
        )

    def generate_json(self, *, system: str, user: str, schema_name: str, schema: dict[str, Any],
                      cache_key: str | None = None) -> LLMResult:
        return with_retries(lambda: self._call(system, user, schema_name, schema), max_retries=self.max_retries)


def make_openai(api_key: str, model: str, timeout_s: float, max_retries: int) -> ChatCompletionsProvider:
    # SDK-level retries disabled: retry policy lives in with_retries so it is visible and tested.
    client = openai.OpenAI(api_key=api_key, timeout=timeout_s, max_retries=0)
    return ChatCompletionsProvider("openai", client, openai, model, strict=True, max_retries=max_retries,
                                   send_temperature=False)


def make_groq(api_key: str, model: str, timeout_s: float, max_retries: int) -> ChatCompletionsProvider:
    client = groq.Groq(api_key=api_key, timeout=timeout_s, max_retries=0)
    return ChatCompletionsProvider("groq", client, groq, model, strict=model in GROQ_STRICT_MODELS,
                                   max_retries=max_retries, send_temperature=True)
