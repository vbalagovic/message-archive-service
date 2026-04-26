"""Runtime configuration for the chat BFF."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    archive_url: str = Field(default="http://api:8000")
    archive_api_key: str = Field(default="dev-key-change-me")

    ollama_url: str = Field(default="http://ollama:11434")
    llm_model: str = Field(default="gemma3:1b")
    llm_system_prompt: str = Field(
        default=(
            "You are a concise, friendly assistant. "
            "Reply in clean Markdown. Keep answers short unless asked otherwise."
        )
    )
    llm_temperature: float = Field(default=0.7)

    request_timeout_s: float = Field(default=120.0)
    log_level: str = Field(default="INFO")

    cors_origins: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
