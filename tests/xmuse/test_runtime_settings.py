"""Tests for the Settings overlay (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from xmuse_core.runtime.settings import Settings, get_settings, validate_runtime_config


class TestSettingsDefaults:
    """Default values are returned when no env vars are set."""

    def test_get_settings_returns_settings_instance(self):
        """get_settings() returns a Settings with defaults."""
        settings = get_settings()
        assert isinstance(settings, Settings)
        assert settings.xmuse_root == Path("./xmuse")
        assert settings.codex_model == "gpt-5.4"
        assert settings.deepseek_api_key == ""
        assert settings.deepseek_model == "deepseek-v4-flash"
        assert settings.runtime_backend == "ray"
        assert settings.review_god_backend == "ray"
        assert settings.execute_god_backend == "ray"
        assert settings.peer_god_backend == "native"
        assert settings.review_gate is True
        assert settings.chat_api_url == "http://127.0.0.1:8201"
        assert settings.superpowers is False


class TestSettingsEnvOverride:
    """Environment variables override defaults."""

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch):
        """Setting an env var changes the corresponding field."""
        monkeypatch.setenv("CODEX_MODEL", "gpt-6.0")
        monkeypatch.setenv("XMUSE_ROOT", "/custom/xmuse")
        monkeypatch.setenv("SUPERPOWERS", "true")
        monkeypatch.setenv("RUNTIME_BACKEND", "process")

        settings = Settings()
        assert settings.codex_model == "gpt-6.0"
        assert settings.xmuse_root == Path("/custom/xmuse")
        assert settings.superpowers is True
        assert settings.runtime_backend == "process"

    def test_deepseek_api_key_override(self, monkeypatch: pytest.MonkeyPatch):
        """DEEPSEEK_API_KEY env var maps to deepseek_api_key field."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-12345")
        settings = Settings()
        assert settings.deepseek_api_key == "sk-test-key-12345"


class TestSettingsFrozen:
    """Settings instances cannot be mutated after creation."""

    def test_cannot_set_attributes(self):
        """Trying to set an attribute on a frozen Settings raises TypeError/YAML."""
        settings = Settings()
        with pytest.raises((ValidationError, TypeError)):
            settings.xmuse_root = Path("/different/path")


class TestValidateRuntimeConfig:
    """validate_runtime_config() returns appropriate warnings."""

    def test_warns_when_key_unset(self, monkeypatch: pytest.MonkeyPatch):
        """Returns warnings when DEEPSEEK_API_KEY is not set."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        # Reset the cached singleton
        from xmuse_core.runtime import settings as settings_module

        settings_module._settings = None
        warnings = validate_runtime_config()
        assert len(warnings) > 0
        assert any("DEEPSEEK_API_KEY" in w for w in warnings)

    def test_empty_when_key_set(self, monkeypatch: pytest.MonkeyPatch):
        """Returns empty list when DEEPSEEK_API_KEY is set."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-for-validation")
        from xmuse_core.runtime import settings as settings_module

        settings_module._settings = None
        warnings = validate_runtime_config()
        assert len(warnings) == 0


class TestSettingsCache:
    """get_settings() caches the Settings instance."""

    def test_singleton_behavior(self, monkeypatch: pytest.MonkeyPatch):
        """get_settings() returns the same instance on repeated calls."""
        from xmuse_core.runtime import settings as settings_module

        settings_module._settings = None
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
