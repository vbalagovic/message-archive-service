"""Runtime configuration, sourced strictly from environment variables.

Twelve-factor: every knob is an env var, every default is dev-friendly only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://archive:archive@localhost:5432/archive",
        description="SQLAlchemy async URL. Must use the asyncpg driver.",
    )

    # --- Auth ---
    # NoDecode tells pydantic-settings not to try JSON-decoding the raw env var;
    # the field_validator below splits the CSV form (KEY=a,b,c) into a list.
    api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["dev-key-change-me"],
        description="Accepted API keys; clients send one in the X-API-Key header.",
    )

    # --- Observability ---
    log_level: str = Field(default="INFO")
    enable_metrics: bool = Field(default=False)

    # --- Limits ---
    rate_limit_per_minute: int = Field(default=120, ge=1)
    max_content_length: int = Field(default=32_768, ge=1)

    # --- CORS ---
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Service identity ---
    service_name: str = Field(default="message-archive")
    environment: str = Field(default="local")

    @field_validator("api_keys", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow `KEY=a,b,c` env values to populate list fields."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver")
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Unsupported log level: {value}")
        return upper

    @property
    def sync_database_url(self) -> str:
        """Sync URL for tools (e.g. Alembic offline mode)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — read once per process."""
    return Settings()
