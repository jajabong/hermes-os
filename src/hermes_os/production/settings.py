"""Environment-based settings for Hermes OS via pydantic-settings.

All settings are prefixed with HERMES_ and loaded from environment variables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_cached_instance: HermesSettings | None = None


def _get_cached_instance() -> HermesSettings | None:
    global _cached_instance
    return _cached_instance


def _clear_cached_instance() -> None:
    """Clear the singleton cache — used by tests to force fresh settings."""
    global _cached_instance
    _cached_instance = None


class HermesSettings(BaseSettings):
    """Hermes OS application settings loaded from HERMES_* environment variables.

    Attributes:
        hermes_db_path: Path to the Hermes SQLite database.
        knowledge_db_path: Path to the knowledge base SQLite database.
        anthropic_api_key: Anthropic API key for LLM calls.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        port: Server port for the gateway hook.
        enable_event_loop: Enable the background event loop.
        enable_proactive: Enable proactive engine.
        enable_health_endpoint: Enable the /health endpoint.
        cors_origins: List of allowed CORS origins.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    hermes_db_path: str = Field(default="hermes.db", validation_alias="HERMES_DB_PATH")
    knowledge_db_path: str = Field(
        default="hermes_knowledge.db", validation_alias="HERMES_KNOWLEDGE_DB_PATH"
    )
    anthropic_api_key: str = Field(default="", validation_alias="HERMES_ANTHROPIC_API_KEY")
    log_level: str = Field(default="INFO", validation_alias="HERMES_LOG_LEVEL")
    port: int = Field(default=8080, validation_alias="HERMES_PORT")

    enable_event_loop: bool = Field(default=True, validation_alias="HERMES_ENABLE_EVENT_LOOP")
    enable_proactive: bool = Field(default=True, validation_alias="HERMES_ENABLE_PROACTIVE")
    enable_health_endpoint: bool = Field(
        default=True, validation_alias="HERMES_ENABLE_HEALTH_ENDPOINT"
    )

    # cors_origins — reads HERMES_CORS_ORIGINS manually to avoid pydantic-settings
    # JSON-list decoding issues with comma-separated values. The validator below
    # handles the parsing from raw env string.
    cors_origins: list[str] = Field(default_factory=list)

    def __new__(cls) -> HermesSettings:
        global _cached_instance
        if _cached_instance is None:
            _cached_instance = super().__new__(cls)
        return _cached_instance

    @staticmethod
    def _clear_cache() -> None:
        """Clear the singleton cache — used by tests."""
        global _cached_instance
        _cached_instance = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse HERMES_CORS_ORIGINS from raw env string or from model data."""
        import os as _os

        raw = _os.environ.get("HERMES_CORS_ORIGINS", "")
        if not raw:
            # Fall back to whatever was passed in (validator chaining)
            if isinstance(v, str) and not v.startswith("[") and "," in v:
                return [s.strip() for s in v.split(",") if s.strip()]
            if isinstance(v, list):
                return v
            return []
        # Try JSON first: ["https://a.com", "https://b.com"]
        if raw.startswith("["):
            import json

            try:
                return json.loads(raw)
            except Exception:
                pass
        # Comma-separated: https://a.com,https://b.com
        return [s.strip() for s in raw.split(",") if s.strip()]

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, v: Any) -> str:
        """Normalize log level to uppercase."""
        return v.upper() if isinstance(v, str) else "INFO"


@lru_cache(maxsize=1)
def get_settings() -> HermesSettings:
    """Return the cached HermesSettings singleton."""
    return HermesSettings()
