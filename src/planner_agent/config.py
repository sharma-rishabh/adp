"""Application configuration loaded from YAML config file + environment secrets.

Non-secret settings (model, timezone, sandbox path, etc.) live in a YAML
config file (default: ``~/.adp/config.yaml``).  Secrets (API keys, bot
tokens) stay in environment variables / ``.env``.

Config file location can be overridden via ``ADP_CONFIG_PATH`` env var.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from planner_agent.exceptions import ConfigValidationError

_DEFAULT_CONFIG_DIR = Path.home() / ".adp"
_DEFAULT_CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.yaml"

# Bundled instruction templates shipped with the package
_BUNDLED_INSTRUCTIONS_DIR = Path(__file__).resolve().parent.parent.parent / "sandbox" / "instructions"


@dataclass(frozen=True)
class AppConfig:
    """Immutable container for all application settings.

    Secrets come from environment variables; everything else from the
    YAML config file with sensible defaults.
    """

    # --- Secrets (env only) ---
    anthropic_api_key: str
    telegram_bot_token: str
    allowed_user_ids: list[str]

    # --- From config file ---
    sandbox_path: str = str(Path.home() / ".adp" / "sandbox")
    claude_model: str = "claude-haiku-4-5-20251001"
    max_agent_turns: int = 10
    timezone: str = "UTC"
    heartbeat_interval_minutes: int = 2
    daily_token_budget: int = 100000
    use_mempalace: bool = True
    system_prompt_path: str = "instructions/system_prompt.md"
    eod_reflection_time: str = "22:30"  # HH:MM in user's timezone

    @classmethod
    def from_file(cls, config_path: Path | None = None) -> AppConfig:
        """Build ``AppConfig`` from YAML config file + environment secrets.

        Args:
            config_path: Override for the YAML config file location.

        Returns:
            A fully-validated ``AppConfig`` instance.

        Raises:
            ConfigValidationError: If required env vars are missing or
                values fail validation.
        """
        # --- Resolve config file path ---
        if config_path is None:
            env_path = os.environ.get("ADP_CONFIG_PATH")
            config_path = Path(env_path) if env_path else _DEFAULT_CONFIG_PATH

        cfg: dict = {}
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
        else:
            # First run — write a default config so the user can edit it
            cfg = generate_default_config()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
            import logging
            logging.getLogger(__name__).info(
                "Created default config at %s — edit to customise.", config_path
            )

        # --- Secrets from env ---
        anthropic_api_key = _require_env("ANTHROPIC_API_KEY")
        telegram_bot_token = _require_env("TELEGRAM_BOT_TOKEN")

        raw_user_ids = _require_env("ALLOWED_TELEGRAM_USER_IDS")
        allowed_user_ids = [uid.strip() for uid in raw_user_ids.split(",") if uid.strip()]
        if not allowed_user_ids:
            raise ConfigValidationError(
                "ALLOWED_TELEGRAM_USER_IDS must contain at least one user ID."
            )

        # --- Config file values with defaults ---
        sandbox_path = str(cfg.get("sandbox_path", Path.home() / ".adp" / "sandbox"))
        claude_model = cfg.get("claude_model", "claude-haiku-4-5-20251001")
        timezone = cfg.get("timezone", "UTC")
        system_prompt_path = cfg.get(
            "system_prompt_path", "instructions/system_prompt.md"
        )
        use_mempalace = bool(cfg.get("use_mempalace", True))

        max_agent_turns = _parse_int(cfg, "max_agent_turns", 10)
        if max_agent_turns < 1:
            raise ConfigValidationError(
                f"max_agent_turns must be >= 1, got {max_agent_turns}."
            )

        heartbeat_interval_minutes = _parse_int(
            cfg, "heartbeat_interval_minutes", 60
        )
        if heartbeat_interval_minutes < 0:
            raise ConfigValidationError(
                f"heartbeat_interval_minutes must be >= 0, got {heartbeat_interval_minutes}."
            )

        daily_token_budget = _parse_int(cfg, "daily_token_budget", 100000)

        eod_reflection_time = str(cfg.get("eod_reflection_time", "22:30"))

        return cls(
            anthropic_api_key=anthropic_api_key,
            telegram_bot_token=telegram_bot_token,
            allowed_user_ids=allowed_user_ids,
            sandbox_path=sandbox_path,
            system_prompt_path=system_prompt_path,
            claude_model=claude_model,
            max_agent_turns=max_agent_turns,
            timezone=timezone,
            heartbeat_interval_minutes=heartbeat_interval_minutes,
            daily_token_budget=daily_token_budget,
            use_mempalace=use_mempalace,
            eod_reflection_time=eod_reflection_time,
        )

    # Keep backward compat — from_env delegates to from_file
    @classmethod
    def from_env(cls) -> AppConfig:
        """Backward-compatible loader — reads YAML config + env secrets."""
        return cls.from_file()

    @staticmethod
    def default_config_path() -> Path:
        return _DEFAULT_CONFIG_PATH

    @staticmethod
    def bundled_instructions_dir() -> Path:
        return _BUNDLED_INSTRUCTIONS_DIR


def generate_default_config(
    sandbox_path: str | None = None,
    timezone: str = "Asia/Kolkata",
    heartbeat_interval_minutes: int = 20,
    daily_token_budget: int = 100000,
    claude_model: str = "claude-haiku-4-5-20251001",
    use_mempalace: bool = True,
) -> dict:
    """Return a config dict with the given values (for writing to YAML)."""
    return {
        "sandbox_path": sandbox_path or str(Path.home() / ".adp" / "sandbox"),
        "claude_model": claude_model,
        "max_agent_turns": 10,
        "timezone": timezone,
        "heartbeat_interval_minutes": heartbeat_interval_minutes,
        "daily_token_budget": daily_token_budget,
        "use_mempalace": use_mempalace,
        "system_prompt_path": "instructions/system_prompt.md",
        "eod_reflection_time": "22:30",
    }


def write_config(config_dict: dict, config_path: Path | None = None) -> Path:
    """Write a config dict to YAML. Returns the path written to."""
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
    return config_path


def seed_sandbox(sandbox_path: str) -> None:
    """Copy bundled instruction templates into the sandbox if missing.

    Creates the sandbox directory structure and copies all instruction
    files from the package's bundled templates.
    """
    sandbox = Path(sandbox_path)
    instructions_dest = sandbox / "instructions"
    instructions_dest.mkdir(parents=True, exist_ok=True)

    src = _BUNDLED_INSTRUCTIONS_DIR
    if not src.exists():
        return

    for template in src.iterdir():
        if template.is_file():
            dest_file = instructions_dest / template.name
            if not dest_file.exists():
                shutil.copy2(template, dest_file)

    # Ensure schedule.md exists with recurring section
    schedule_file = sandbox / "schedule.md"
    if not schedule_file.exists():
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        schedule_file.write_text(
            "## Recurring\n\n"
            "<!-- Add your daily routines here -->\n\n"
            f"## Today ({today})\n\n"
            "<!-- Today's schedule will be written here -->\n"
        )


def _require_env(name: str) -> str:
    """Return an env var's value or raise if missing/empty."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigValidationError(
            f"Required environment variable '{name}' is missing or empty."
        )
    return value


def _parse_int(cfg: dict, key: str, default: int) -> int:
    """Parse an integer from the config dict with a default."""
    raw = cfg.get(key, default)
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise ConfigValidationError(
            f"{key} must be an integer, got '{raw}'."
        ) from None

