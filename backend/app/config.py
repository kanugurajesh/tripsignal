"""Settings loaded from environment / .env. Validated at startup."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["openai", "groq", "oracle"]

# Defaults verified against official docs on 2026-10-20 (see docs/DECISIONS.md D5).
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_OPENAI_MODEL = "gpt-6.1-sol"

# USD per 1M tokens (input, output) from the providers' public pricing pages on 2026-10-20.
# Unknown models report cost as None rather than guessing.
PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "gpt-6-astra": (10.0, 50.0),
    "gpt-6.1-sol": (2.0, 10.0),
    "gpt-6-luna": (0.10, 0.50),
}


class ConfigError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    ai_provider: ProviderName = "oracle"
    fallback_provider: ProviderName | None = None
    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    groq_model: str = DEFAULT_GROQ_MODEL
    openai_model: str = DEFAULT_OPENAI_MODEL
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    llm_narratives: bool = True
    database_url: str = "sqlite:///./tripsignal.db"
    as_of_date: date | None = None  # fixes "today" for reproducible demos
    cors_origins: str = "http://localhost:3000"

    def model_for(self, provider: ProviderName) -> str:
        return {"groq": self.groq_model, "openai": self.openai_model, "oracle": "ground-truth"}[provider]

    def validate_provider(self, provider: ProviderName) -> None:
        key = {"groq": self.groq_api_key, "openai": self.openai_api_key}.get(provider)
        if provider in ("groq", "openai") and (key is None or not key.get_secret_value().strip()):
            env = f"{provider.upper()}_API_KEY"
            raise ConfigError(
                f"AI_PROVIDER={provider} but {env} is not set. Add it to backend/.env "
                f"(see .env.example) or use AI_PROVIDER=oracle for the offline demo."
            )

    def validate_startup(self) -> None:
        self.validate_provider(self.ai_provider)
        if self.fallback_provider:
            if self.fallback_provider == self.ai_provider:
                raise ConfigError("FALLBACK_PROVIDER must differ from AI_PROVIDER")
            self.validate_provider(self.fallback_provider)


@lru_cache
def get_settings() -> Settings:
    return Settings()
