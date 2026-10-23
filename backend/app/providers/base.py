"""Provider abstraction: one capability (schema-constrained JSON generation),
typed errors, bounded retries, and usage/cost accounting."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import PRICING


class ProviderError(Exception):
    retryable = False

    def __init__(self, provider: str, message: str):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderRateLimited(ProviderError):
    retryable = True

    def __init__(self, provider: str, message: str, retry_after: float | None = None):
        super().__init__(provider, message)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    retryable = True


class ProviderAuthError(ProviderError):
    pass


class ProviderQuotaExhausted(ProviderError):
    """Billing/quota exhausted: retrying cannot help."""


class ProviderBadResponse(ProviderError):
    """Model returned something that is not valid JSON / not the schema."""


class CapabilityNotSupported(ProviderError):
    pass


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    attempts: int = 1
    structured_mode: str = "json_schema_strict"
    fallback_from: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def cost_usd(self) -> float | None:
        price = PRICING.get(self.model)
        if price is None or self.input_tokens is None or self.output_tokens is None:
            return None
        return (self.input_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000

    def usage(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "model": self.model, "latency_ms": round(self.latency_ms, 1),
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd, "attempts": self.attempts,
            "structured_mode": self.structured_mode, "fallback_from": self.fallback_from,
        }


class LLMProvider(Protocol):
    name: str
    model: str
    supports_narrative: bool

    def generate_json(
        self, *, system: str, user: str, schema_name: str, schema: dict[str, Any], cache_key: str | None = None
    ) -> LLMResult: ...


def with_retries(
    fn: Callable[[], LLMResult], *, max_retries: int, sleep: Callable[[float], None] = time.sleep
) -> LLMResult:
    """Retry only retryable errors, with bounded exponential backoff."""
    attempt = 0
    while True:
        attempt += 1
        try:
            res = fn()
            res.attempts = attempt
            return res
        except ProviderError as e:
            if not e.retryable or attempt > max_retries:
                raise
            wait = float(min(2 ** (attempt - 1), 8))
            if isinstance(e, ProviderRateLimited) and e.retry_after:
                wait = max(wait, min(e.retry_after, 60.0))  # honour the server's retry-after, capped
            sleep(wait)


class FallbackProvider:
    """Primary provider with an explicit, recorded fallback (opt-in via FALLBACK_PROVIDER).
    Only infrastructure errors fall back; a bad model response does not."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary, self.fallback = primary, fallback
        self.name, self.model = primary.name, primary.model
        self.supports_narrative = primary.supports_narrative

    def generate_json(self, **kw: Any) -> LLMResult:
        try:
            return self.primary.generate_json(**kw)
        except (ProviderTimeout, ProviderRateLimited, ProviderUnavailable, ProviderAuthError, ProviderQuotaExhausted) as e:
            res = self.fallback.generate_json(**kw)
            res.fallback_from = self.primary.name
            res.notes.append(f"fallback after: {e}")
            return res


def strict_schema(model_cls: Any) -> dict[str, Any]:
    """Pydantic JSON schema -> strict-mode compatible schema (inlined refs,
    every property required, no additionalProperties, no defaults/titles)."""
    raw = model_cls.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            out = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)
