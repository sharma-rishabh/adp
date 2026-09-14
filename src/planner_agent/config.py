"""Application configuration loaded from YAML config file + environment secrets.

Non-secret settings (model, timezone, sandbox path, etc.) live in a YAML
config file (default: ``~/.adp/config.yaml``).  Secrets (API keys, bot
tokens) stay in environment variables / ``.env``.

Config file location can be overridden via ``ADP_CONFIG_PATH`` env var.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from planner_agent.exceptions import ConfigValidationError

_DEFAULT_CONFIG_DIR = Path.home() / ".adp"
_DEFAULT_CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.yaml"
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _coerce_hhmm(value: object, key: str) -> str:
    """Coerce a config time value to a validated 'HH:MM' string.

    YAML 1.1 parses an unquoted bare ``HH:MM`` as a sexagesimal integer
    (``13:00`` -> ``780``) whenever the hour is >= 10, which is exactly how
    a human editing this file by hand would write it. Recover the original
    HH:MM from that integer before validating.
    """
    if isinstance(value, int):
        value = f"{value // 60:02d}:{value % 60:02d}"
    text = str(value).strip()
    if not _HHMM_RE.match(text):
        raise ConfigValidationError(f"{key} must be HH:MM, got {value!r}.")
    return text

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
    reflection_model: str = "claude-sonnet-5"  # smarter model for EOD reflections
    max_agent_turns: int = 10
    timezone: str = "UTC"
    nudge_times: list[str] = field(default_factory=lambda: ["09:00", "13:00", "18:00"])
    nudge_backoff_threshold: int = 3  # consecutive ignored nudges before backing off
    daily_token_budget: int = 100000
    use_mempalace: bool = True
    system_prompt_path: str = "instructions/system_prompt.md"
    eod_reflection_time: str = "22:30"  # HH:MM in user's timezone
    quiet_hours_start: str = "23:00"  # HH:MM — heartbeat paused from this time
    quiet_hours_end: str = "09:00"    # HH:MM — heartbeat resumes at this time

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
        reflection_model = cfg.get("reflection_model", "claude-sonnet-5")
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

        nudge_times = [
            _coerce_hhmm(t, "nudge_times")
            for t in cfg.get("nudge_times", ["09:00", "13:00", "18:00"])
        ]

        nudge_backoff_threshold = _parse_int(cfg, "nudge_backoff_threshold", 3)
        if nudge_backoff_threshold < 1:
            raise ConfigValidationError(
                f"nudge_backoff_threshold must be >= 1, got {nudge_backoff_threshold}."
            )

        daily_token_budget = _parse_int(cfg, "daily_token_budget", 100000)

        eod_reflection_time = _coerce_hhmm(cfg.get("eod_reflection_time", "22:30"), "eod_reflection_time")
        quiet_hours_start = _coerce_hhmm(cfg.get("quiet_hours_start", "23:00"), "quiet_hours_start")
        quiet_hours_end = _coerce_hhmm(cfg.get("quiet_hours_end", "09:00"), "quiet_hours_end")

        return cls(
            anthropic_api_key=anthropic_api_key,
            telegram_bot_token=telegram_bot_token,
            allowed_user_ids=allowed_user_ids,
            sandbox_path=sandbox_path,
            system_prompt_path=system_prompt_path,
            claude_model=claude_model,
            reflection_model=reflection_model,
            max_agent_turns=max_agent_turns,
            timezone=timezone,
            nudge_times=nudge_times,
            nudge_backoff_threshold=nudge_backoff_threshold,
            daily_token_budget=daily_token_budget,
            use_mempalace=use_mempalace,
            eod_reflection_time=eod_reflection_time,
            quiet_hours_start=quiet_hours_start,
            quiet_hours_end=quiet_hours_end,
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
    nudge_times: list[str] | None = None,
    nudge_backoff_threshold: int = 3,
    daily_token_budget: int = 100000,
    claude_model: str = "claude-haiku-4-5-20251001",
    use_mempalace: bool = True,
    reflection_model: str = "claude-sonnet-5",
) -> dict:
    """Return a config dict with the given values (for writing to YAML)."""
    return {
        "sandbox_path": sandbox_path or str(Path.home() / ".adp" / "sandbox"),
        "claude_model": claude_model,
        "reflection_model": reflection_model,
        "max_agent_turns": 10,
        "timezone": timezone,
        "nudge_times": ["09:00", "13:00", "18:00"] if nudge_times is None else nudge_times,
        "nudge_backoff_threshold": nudge_backoff_threshold,
        "daily_token_budget": daily_token_budget,
        "use_mempalace": use_mempalace,
        "system_prompt_path": "instructions/system_prompt.md",
        "eod_reflection_time": "22:30",
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "09:00",
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

    # Ensure todos.md and goals.md exist (action items + long-term goals)
    todos_file = sandbox / "todos.md"
    if not todos_file.exists():
        todos_file.write_text(
            "# TODOs\n\n"
            "<!-- Open: - [ ] task (added YYYY-MM-DD) | Done: - [x] task (done YYYY-MM-DD) -->\n"
        )
    goals_file = sandbox / "goals.md"
    if not goals_file.exists():
        goals_file.write_text(
            "# Long-term goals\n\n<!-- One goal per line -->\n"
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

