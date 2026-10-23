"""Providers that make no network calls.

OracleProvider replays ground-truth extractions from the synthetic dataset. It
exists so the demo and CI run without keys and so the deterministic engine can
be evaluated in isolation. Its output is always labelled provider="oracle" and
is never presented as model output.

ScriptedProvider returns queued responses or raises queued errors (tests).
"""

from __future__ import annotations

from typing import Any

from app.providers.base import CapabilityNotSupported, LLMResult, ProviderError


class OracleProvider:
    name = "oracle"
    model = "ground-truth"
    supports_narrative = False

    def __init__(self, gold: dict[str, dict[str, Any]]):
        self.gold = gold

    def generate_json(self, *, system: str, user: str, schema_name: str, schema: dict[str, Any],
                      cache_key: str | None = None) -> LLMResult:
        if schema_name != "contract_extraction":
            raise CapabilityNotSupported(self.name, f"oracle cannot generate {schema_name}")
        if cache_key not in self.gold:
            raise CapabilityNotSupported(self.name, f"no ground truth for document {cache_key}")
        return LLMResult(data=self.gold[cache_key], provider=self.name, model=self.model, latency_ms=0.0,
                         input_tokens=0, output_tokens=0, structured_mode="oracle")


class ScriptedProvider:
    def __init__(self, items: list[dict[str, Any] | Exception], name: str = "scripted", model: str = "scripted-1"):
        self.items = list(items)
        self.name, self.model = name, model
        self.supports_narrative = True
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, **kw: Any) -> LLMResult:
        self.calls.append(kw)
        if not self.items:
            raise ProviderError(self.name, "script exhausted")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(data=item, provider=self.name, model=self.model, latency_ms=1.0,
                         input_tokens=100, output_tokens=50)
