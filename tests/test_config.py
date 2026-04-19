"""Tests for AppConfig.

Covers: successful loading, missing required vars, invalid values,
and default fallbacks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from planner_agent.config import AppConfig
from planner_agent.exceptions import ConfigValidationError


@pytest.fixture()
def _env_vars(monkeypatch):
    """Set up a minimal valid environment for AppConfig."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "111,222")


class TestFromEnv:
    """Tests for AppConfig.from_env."""

    @pytest.mark.usefixtures("_env_vars")
    def test_loads_required_values(self):
        config = AppConfig.from_env()
        assert config.anthropic_api_key == "sk-test-key"
        assert config.telegram_bot_token == "123:ABC"
        assert config.allowed_user_ids == ["111", "222"]

    @pytest.mark.usefixtures("_env_vars")
    def test_defaults(self):
        config = AppConfig.from_env()
        assert config.sandbox_path == str(Path.home() / ".adp" / "sandbox")
        assert config.system_prompt_path == "instructions/system_prompt.md"
        assert config.claude_model == "claude-3-5-haiku-latest"
        assert config.max_agent_turns == 10
        assert config.timezone == "UTC"
        assert config.heartbeat_interval_minutes == 60
        assert config.daily_token_budget == 100000

    @pytest.mark.usefixtures("_env_vars")
    def test_custom_overrides(self, monkeypatch):
        monkeypatch.setenv("SANDBOX_PATH", "/custom/sandbox")
        monkeypatch.setenv("SYSTEM_PROMPT_PATH", "prompts/custom.md")
        monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-4-20250514")
        monkeypatch.setenv("MAX_AGENT_TURNS", "5")
        monkeypatch.setenv("TIMEZONE", "Asia/Kolkata")
        monkeypatch.setenv("HEARTBEAT_INTERVAL_MINUTES", "30")
        monkeypatch.setenv("DAILY_TOKEN_BUDGET", "50000")
        config = AppConfig.from_env()
        assert config.sandbox_path == "/custom/sandbox"
        assert config.system_prompt_path == "prompts/custom.md"
        assert config.claude_model == "claude-opus-4-20250514"
        assert config.max_agent_turns == 5
        assert config.timezone == "Asia/Kolkata"
        assert config.heartbeat_interval_minutes == 30
        assert config.daily_token_budget == 50000


class TestMissingEnvVars:
    """Tests for missing/empty required environment variables."""

    def test_missing_anthropic_key_raises(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "111")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ConfigValidationError, match="ANTHROPIC_API_KEY"):
            AppConfig.from_env()

    def test_missing_bot_token_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "111")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(ConfigValidationError, match="TELEGRAM_BOT_TOKEN"):
            AppConfig.from_env()

    def test_missing_user_ids_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.delenv("ALLOWED_TELEGRAM_USER_IDS", raising=False)
        with pytest.raises(ConfigValidationError, match="ALLOWED_TELEGRAM_USER_IDS"):
            AppConfig.from_env()

    def test_empty_user_ids_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "  ,  , ")
        with pytest.raises(ConfigValidationError, match="at least one user ID"):
            AppConfig.from_env()


class TestInvalidValues:
    """Tests for invalid configuration values."""

    @pytest.mark.usefixtures("_env_vars")
    def test_non_integer_max_turns_raises(self, monkeypatch):
        monkeypatch.setenv("MAX_AGENT_TURNS", "abc")
        with pytest.raises(ConfigValidationError, match="integer"):
            AppConfig.from_env()

    @pytest.mark.usefixtures("_env_vars")
    def test_zero_max_turns_raises(self, monkeypatch):
        monkeypatch.setenv("MAX_AGENT_TURNS", "0")
        with pytest.raises(ConfigValidationError, match=">= 1"):
            AppConfig.from_env()

    @pytest.mark.usefixtures("_env_vars")
    def test_negative_max_turns_raises(self, monkeypatch):
        monkeypatch.setenv("MAX_AGENT_TURNS", "-3")
        with pytest.raises(ConfigValidationError, match=">= 1"):
            AppConfig.from_env()

