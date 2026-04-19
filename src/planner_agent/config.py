"""Application configuration loaded from environment variables.

This is the single place in the codebase that reads from ``os.environ``.
All other modules receive their configuration via constructor injection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from planner_agent.exceptions import ConfigValidationError


@dataclass(frozen=True)
class AppConfig:
    """Immutable container for all application settings.

    Attributes:
        anthropic_api_key: API key for Anthropic Claude.
        telegram_bot_token: Bot token from BotFather.
        allowed_user_ids: Telegram user IDs permitted to use the bot.
        sandbox_path: Filesystem path to the sandbox root directory.
        system_prompt_path: Relative path (within the sandbox) to the
            system prompt file.
        claude_model: Claude model identifier (e.g. ``claude-3-5-haiku-latest``).
        max_agent_turns: Maximum tool-use loop iterations per request.
        timezone: IANA timezone string for the user (e.g. ``Asia/Kolkata``).
        heartbeat_interval_minutes: How often (in minutes) the heartbeat
            wakes up.  The agent decides whether to nudge.  0 disables.
        daily_token_budget: Daily token budget for the progress bar.
            0 disables the progress bar.
    """

    anthropic_api_key: str
    telegram_bot_token: str
    allowed_user_ids: list[str]
    sandbox_path: str
    system_prompt_path: str
    claude_model: str
    max_agent_turns: int
    timezone: str

    heartbeat_interval_minutes: int
    daily_token_budget: int
    use_mempalace: bool

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build an ``AppConfig`` from environment variables.

        Reads values from the current ``os.environ``.  Call
        ``dotenv.load_dotenv()`` **before** invoking this method if you
        want ``.env`` file support.

        Returns:
            A fully-validated ``AppConfig`` instance.

        Raises:
            ConfigValidationError: If any required variable is missing
                or a value fails validation.
        """
        anthropic_api_key = _require_env("ANTHROPIC_API_KEY")
        telegram_bot_token = _require_env("TELEGRAM_BOT_TOKEN")

        raw_user_ids = _require_env("ALLOWED_TELEGRAM_USER_IDS")
        allowed_user_ids = [uid.strip() for uid in raw_user_ids.split(",") if uid.strip()]
        if not allowed_user_ids:
            raise ConfigValidationError("ALLOWED_TELEGRAM_USER_IDS must contain at least one user ID.")

        _default_sandbox = str(Path.home() / ".adp" / "sandbox")
        sandbox_path = os.environ.get("SANDBOX_PATH", _default_sandbox)
        system_prompt_path = os.environ.get("SYSTEM_PROMPT_PATH", "instructions/system_prompt.md")
        claude_model = os.environ.get("CLAUDE_MODEL", "claude-3-5-haiku-latest")
        timezone = os.environ.get("TIMEZONE", "UTC")

        raw_turns = os.environ.get("MAX_AGENT_TURNS", "10")
        try:
            max_agent_turns = int(raw_turns)
        except ValueError:
            raise ConfigValidationError(f"MAX_AGENT_TURNS must be an integer, got '{raw_turns}'.") from None

        if max_agent_turns < 1:
            raise ConfigValidationError(f"MAX_AGENT_TURNS must be >= 1, got {max_agent_turns}.")

        raw_heartbeat = os.environ.get("HEARTBEAT_INTERVAL_MINUTES", "60")
        try:
            heartbeat_interval_minutes = int(raw_heartbeat)
        except ValueError:
            raise ConfigValidationError(
                f"HEARTBEAT_INTERVAL_MINUTES must be an integer, got '{raw_heartbeat}'."
            ) from None

        if heartbeat_interval_minutes < 0:
            raise ConfigValidationError(
                f"HEARTBEAT_INTERVAL_MINUTES must be >= 0, got {heartbeat_interval_minutes}."
            )

        raw_budget = os.environ.get("DAILY_TOKEN_BUDGET", "100000")
        try:
            daily_token_budget = int(raw_budget)
        except ValueError:
            raise ConfigValidationError(
                f"DAILY_TOKEN_BUDGET must be an integer, got '{raw_budget}'."
            ) from None

        use_mempalace = os.environ.get("USE_MEMPALACE", "true").lower() == "true"

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
        )


def _require_env(name: str) -> str:
    """Return an environment variable's value or raise if missing/empty.

    Args:
        name: The environment variable name.

    Returns:
        The non-empty string value.

    Raises:
        ConfigValidationError: If the variable is unset or blank.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigValidationError(f"Required environment variable '{name}' is missing or empty.")
    return value

