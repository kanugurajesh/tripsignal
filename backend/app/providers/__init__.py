"""Provider factory. Business logic depends only on the LLMProvider protocol."""

from __future__ import annotations

from typing import Any

from app.config import ProviderName, Settings
from app.providers.base import FallbackProvider, LLMProvider


def build_provider(settings: Settings, name: ProviderName | None = None,
                   gold: dict[str, dict[str, Any]] | None = None) -> LLMProvider:
    name = name or settings.ai_provider
    primary = _build_one(settings, name, gold)
    fb = settings.fallback_provider
    if fb and fb != name and name != "oracle":
        return FallbackProvider(primary, _build_one(settings, fb, gold))
    return primary


def _build_one(settings: Settings, name: ProviderName, gold: dict[str, dict[str, Any]] | None) -> LLMProvider:
    settings.validate_provider(name)
    if name == "openai":
        from app.providers.chat import make_openai

        assert settings.openai_api_key
        return make_openai(settings.openai_api_key.get_secret_value(), settings.openai_model,
                           settings.llm_timeout_s, settings.llm_max_retries)
    if name == "groq":
        from app.providers.chat import make_groq

        assert settings.groq_api_key
        return make_groq(settings.groq_api_key.get_secret_value(), settings.groq_model,
                         settings.llm_timeout_s, settings.llm_max_retries)
    from app.providers.offline import OracleProvider

    if gold is None:
        from app.gold import load_gold

        gold = load_gold()
    return OracleProvider(gold)
