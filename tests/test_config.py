"""Tests for AppConfig.

Covers: successful loading from YAML + env, missing required vars,
invalid values, and default fallbacks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from planner_agent.config import AppConfig, generate_default_config, write_config, seed_sandbox
from planner_agent.exceptions import ConfigValidationError


@pytest.fixture()
def _env_vars(monkeypatch):
    """Set up a minimal valid environment for AppConfig."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "111,222")


@pytest.fixture()
def config_path(tmp_path):
    """Return a temp config path (file does not exist yet)."""
    return tmp_path / "config.yaml"


class TestFromFile:
    """Tests for AppConfig.from_file with YAML config."""

    @pytest.mark.usefixtures("_env_vars")
    def test_loads_secrets_from_env(self, config_path):
        config = AppConfig.from_file(config_path)
        assert config.anthropic_api_key == "sk-test-key"
        assert config.telegram_bot_token == "123:ABC"
        assert config.allowed_user_ids == ["111", "222"]

    @pytest.mark.usefixtures("_env_vars")
    def test_defaults_when_no_config_file(self, config_path):
        config = AppConfig.from_file(config_path)
        assert config.sandbox_path == str(Path.home() / ".adp" / "sandbox")
        assert config.system_prompt_path == "instructions/system_prompt.md"
        assert config.claude_model == "claude-haiku-4-5-20251001"
        assert config.max_agent_turns == 10
        assert config.timezone == "Asia/Kolkata"  # default from generate_default_config
        assert config.nudge_times == ["09:00", "13:00", "18:00"]
        assert config.nudge_backoff_threshold == 3
        assert config.daily_token_budget == 100000
        assert config.use_mempalace is True
        # Config file should have been auto-created
        assert config_path.exists()

    @pytest.mark.usefixtures("_env_vars")
    def test_reads_yaml_overrides(self, config_path):
        cfg = {
            "sandbox_path": "/custom/sandbox",
            "claude_model": "claude-opus-4-20250514",
            "max_agent_turns": 5,
            "timezone": "Asia/Kolkata",
            "nudge_times": ["08:00", "17:00"],
            "nudge_backoff_threshold": 5,
            "daily_token_budget": 50000,
            "use_mempalace": False,
        }
        config_path.write_text(yaml.dump(cfg))
        config = AppConfig.from_file(config_path)
        assert config.sandbox_path == "/custom/sandbox"
        assert config.claude_model == "claude-opus-4-20250514"
        assert config.max_agent_turns == 5
        assert config.timezone == "Asia/Kolkata"
        assert config.nudge_times == ["08:00", "17:00"]
        assert config.nudge_backoff_threshold == 5
        assert config.daily_token_budget == 50000
        assert config.use_mempalace is False


class TestFromEnvBackcompat:
    """Ensure from_env still works (delegates to from_file)."""

    @pytest.mark.usefixtures("_env_vars")
    def test_from_env_works(self, monkeypatch, config_path):
        monkeypatch.setenv("ADP_CONFIG_PATH", str(config_path))
        config = AppConfig.from_env()
        assert config.anthropic_api_key == "sk-test-key"


class TestMissingEnvVars:
    """Tests for missing/empty required environment variables."""

    def test_missing_anthropic_key_raises(self, monkeypatch, config_path):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "111")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ConfigValidationError, match="ANTHROPIC_API_KEY"):
            AppConfig.from_file(config_path)

    def test_missing_bot_token_raises(self, monkeypatch, config_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "111")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(ConfigValidationError, match="TELEGRAM_BOT_TOKEN"):
            AppConfig.from_file(config_path)

    def test_missing_user_ids_raises(self, monkeypatch, config_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.delenv("ALLOWED_TELEGRAM_USER_IDS", raising=False)
        with pytest.raises(ConfigValidationError, match="ALLOWED_TELEGRAM_USER_IDS"):
            AppConfig.from_file(config_path)

    def test_empty_user_ids_raises(self, monkeypatch, config_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "  ,  , ")
        with pytest.raises(ConfigValidationError, match="at least one user ID"):
            AppConfig.from_file(config_path)


class TestInvalidValues:
    """Tests for invalid configuration values."""

    @pytest.mark.usefixtures("_env_vars")
    def test_zero_max_turns_raises(self, config_path):
        config_path.write_text(yaml.dump({"max_agent_turns": 0}))
        with pytest.raises(ConfigValidationError, match=">= 1"):
            AppConfig.from_file(config_path)

    @pytest.mark.usefixtures("_env_vars")
    def test_zero_backoff_threshold_raises(self, config_path):
        config_path.write_text(yaml.dump({"nudge_backoff_threshold": 0}))
        with pytest.raises(ConfigValidationError, match=">= 1"):
            AppConfig.from_file(config_path)


class TestTimeCoercion:
    """Tests for _coerce_hhmm — guards against YAML parsing bare HH:MM as int."""

    @pytest.mark.usefixtures("_env_vars")
    def test_yaml_sexagesimal_int_is_recovered(self, config_path):
        # A hand-edited config with unquoted times: YAML 1.1 parses "13:00"
        # as the int 780 and "18:00" as 1080.
        config_path.write_text("nudge_times: [9:00, 13:00, 18:00]\neod_reflection_time: 22:30\n")
        config = AppConfig.from_file(config_path)
        assert config.nudge_times == ["09:00", "13:00", "18:00"]
        assert config.eod_reflection_time == "22:30"

    @pytest.mark.usefixtures("_env_vars")
    def test_malformed_time_raises(self, config_path):
        config_path.write_text(yaml.dump({"eod_reflection_time": "25:99"}))
        with pytest.raises(ConfigValidationError, match="HH:MM"):
            AppConfig.from_file(config_path)

    @pytest.mark.usefixtures("_env_vars")
    def test_malformed_nudge_time_raises(self, config_path):
        config_path.write_text(yaml.dump({"nudge_times": ["not-a-time"]}))
        with pytest.raises(ConfigValidationError, match="HH:MM"):
            AppConfig.from_file(config_path)


class TestGenerateConfig:
    def test_generates_defaults(self):
        cfg = generate_default_config()
        assert cfg["timezone"] == "Asia/Kolkata"
        assert cfg["nudge_times"] == ["09:00", "13:00", "18:00"]
        assert cfg["use_mempalace"] is True

    def test_write_and_read_roundtrip(self, tmp_path):
        path = tmp_path / "config.yaml"
        cfg = generate_default_config(timezone="US/Pacific")
        write_config(cfg, path)
        loaded = yaml.safe_load(path.read_text())
        assert loaded["timezone"] == "US/Pacific"


class TestSeedSandbox:
    def test_creates_schedule_md(self, tmp_path):
        sandbox = str(tmp_path / "sandbox")
        seed_sandbox(sandbox)
        schedule = Path(sandbox) / "schedule.md"
        assert schedule.exists()
        content = schedule.read_text()
        assert "## Recurring" in content
        assert "## Today" in content

    def test_does_not_overwrite_existing(self, tmp_path):
        sandbox = str(tmp_path / "sandbox")
        schedule = Path(sandbox) / "schedule.md"
        schedule.parent.mkdir(parents=True)
        schedule.write_text("custom content")
        seed_sandbox(sandbox)
        assert schedule.read_text() == "custom content"
