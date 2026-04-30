"""Tests for Hermes OS environment-based settings via pydantic-settings."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestHermesSettings:
    """Tests for HermesSettings loaded from environment variables."""

    def test_settings_loads_hermes_db_path_from_env(self) -> None:
        """HERMES_DB_PATH env var sets database path."""
        with patch.dict(os.environ, {"HERMES_DB_PATH": "/custom/path/hermes.db"}):
            from hermes_os.production.settings import HermesSettings
            settings = HermesSettings()
            assert settings.hermes_db_path == "/custom/path/hermes.db"

    def test_settings_loads_knowledge_db_path_from_env(self) -> None:
        """HERMES_KNOWLEDGE_DB_PATH env var sets knowledge base path."""
        with patch.dict(os.environ, {"HERMES_KNOWLEDGE_DB_PATH": "/custom/path/kb.db"}):
            from hermes_os.production.settings import HermesSettings
            settings = HermesSettings()
            assert settings.knowledge_db_path == "/custom/path/kb.db"

    def test_settings_loads_api_key_from_env(self) -> None:
        """HERMES_ANTHROPIC_API_KEY env var sets the API key."""
        with patch.dict(os.environ, {"HERMES_ANTHROPIC_API_KEY": "sk-ant-test123"}):
            from hermes_os.production.settings import HermesSettings
            settings = HermesSettings()
            assert settings.anthropic_api_key == "sk-ant-test123"

    def test_settings_loads_log_level_from_env(self) -> None:
        """HERMES_LOG_LEVEL env var sets log level."""
        with patch.dict(os.environ, {"HERMES_LOG_LEVEL": "DEBUG"}):
            from hermes_os.production.settings import HermesSettings
            settings = HermesSettings()
            assert settings.log_level == "DEBUG"

    def test_settings_defaults_when_env_not_set(self) -> None:
        """When env vars are not set, defaults are used."""
        env = {
            k: v for k, v in os.environ.items()
            if k.startswith("HERMES_")
        }
        # Clear hermes env vars for this test
        with patch.dict(os.environ, {k: "" for k in env}, clear=False):
            # Remove HERMES_ keys to test defaults
            for k in list(os.environ.keys()):
                if k.startswith("HERMES_"):
                    del os.environ[k]
            from hermes_os.production.settings import HermesSettings
            settings = HermesSettings()
            assert settings.hermes_db_path == "hermes.db"
            assert settings.knowledge_db_path == "hermes_knowledge.db"
            assert settings.log_level == "INFO"

    def test_settings_feature_flags(self) -> None:
        """HERMES_ENABLE_* feature flags are parsed as booleans."""
        with patch.dict(os.environ, {
            "HERMES_ENABLE_EVENT_LOOP": "true",
            "HERMES_ENABLE_PROACTIVE": "false",
        }):
            from hermes_os.production.settings import HermesSettings
            settings = HermesSettings()
            assert settings.enable_event_loop is True
            assert settings.enable_proactive is False

    def test_settings_port(self) -> None:
        """HERMES_PORT env var sets the server port."""
        with patch.dict(os.environ, {"HERMES_PORT": "9000"}):
            from hermes_os.production.settings import HermesSettings
            settings = HermesSettings()
            assert settings.port == 9000

    def test_settings_is_singleton(self) -> None:
        """Settings instance is reused on subsequent imports."""
        from hermes_os.production.settings import HermesSettings
        settings1 = HermesSettings()
        settings2 = HermesSettings()
        assert settings1 is settings2

    def test_settings_health_check_endpoint_enabled_by_default(self) -> None:
        """Health check endpoint is enabled by default."""
        from hermes_os.production.settings import HermesSettings
        settings = HermesSettings()
        assert settings.enable_health_endpoint is True

    def test_settings_cors_origins_from_env(self) -> None:
        """HERMES_CORS_ORIGINS env var is parsed as comma-separated list."""
        with patch.dict(os.environ, {"HERMES_CORS_ORIGINS": "https://a.com,https://b.com"}):
            from hermes_os.production.settings import HermesSettings
            settings = HermesSettings()
            assert settings.cors_origins == ["https://a.com", "https://b.com"]
