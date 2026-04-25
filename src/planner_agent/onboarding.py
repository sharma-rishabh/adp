"""Interactive onboarding — sets up config, sandbox, and schedule for a new user.

Run via ``planner-setup`` console script or ``python -m planner_agent.onboarding``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from planner_agent.config import (
    generate_default_config,
    seed_sandbox,
    write_config,
    _DEFAULT_CONFIG_PATH,
)


def _ask(prompt: str, default: str = "") -> str:
    """Prompt the user with an optional default."""
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _ask_bool(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "true", "1")


def _ask_recurring_schedule() -> str:
    """Interactively collect recurring daily routines."""
    print("\n📅 Let's capture your recurring daily schedule.")
    print("   Enter time blocks one per line (e.g. '7:00-9:00am Gym').")
    print("   Press Enter on an empty line when done.\n")

    lines: list[str] = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        lines.append(f"- {line}")

    if not lines:
        return "- <!-- Add your daily routines here -->"
    return "\n".join(lines)


def _ask_nudge_preferences() -> str:
    """Collect nudge preferences as free-form text."""
    print("\n🔔 Nudge preferences (optional).")
    print("   Describe when you do NOT want nudges and any preferences.")
    print("   Press Enter on an empty line when done.\n")

    lines: list[str] = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        lines.append(line)

    return "\n".join(lines) if lines else ""


def run_onboarding() -> None:
    """Interactive setup wizard for a new ADP user."""
    print("=" * 50)
    print("  🗓️  Agentic Day Planner — Setup Wizard")
    print("=" * 50)

    # --- Config values ---
    sandbox_path = _ask("Sandbox path", str(Path.home() / ".adp" / "sandbox"))
    timezone = _ask("Timezone (IANA)", "Asia/Kolkata")
    claude_model = _ask("Claude model", "claude-haiku-4-5-20251001")
    heartbeat = int(_ask("Heartbeat interval (minutes, 0=off)", "20"))
    token_budget = int(_ask("Daily token budget", "100000"))
    use_mempalace = _ask_bool("Enable MemPalace semantic memory?", True)

    config_dict = generate_default_config(
        sandbox_path=sandbox_path,
        timezone=timezone,
        heartbeat_interval_minutes=heartbeat,
        daily_token_budget=token_budget,
        claude_model=claude_model,
        use_mempalace=use_mempalace,
    )

    # --- Write config ---
    config_path = write_config(config_dict)
    print(f"\n✅ Config written to {config_path}")

    # --- Seed sandbox with instruction templates ---
    seed_sandbox(sandbox_path)
    print(f"✅ Sandbox seeded at {sandbox_path}")

    # --- Recurring schedule ---
    recurring = _ask_recurring_schedule()
    schedule_file = Path(sandbox_path) / "schedule.md"
    schedule_file.write_text(
        f"## Recurring\n\n{recurring}\n\n"
        f"## Today\n\n<!-- Today's schedule will be written here -->\n"
    )
    print("✅ Schedule saved")

    # --- Nudge preferences ---
    nudge_prefs = _ask_nudge_preferences()
    if nudge_prefs:
        nudge_file = Path(sandbox_path) / "instructions" / "nudge.md"
        if nudge_file.exists():
            existing = nudge_file.read_text()
            # Append user preferences at the end
            nudge_file.write_text(
                existing.rstrip() + "\n\n## Your Preferences\n" + nudge_prefs + "\n"
            )
        print("✅ Nudge preferences saved")

    # --- Remind about secrets ---
    print("\n" + "-" * 50)
    print("⚠️  Secrets go in your .env file (not in config.yaml):")
    print("   ANTHROPIC_API_KEY=sk-ant-...")
    print("   TELEGRAM_BOT_TOKEN=123:ABC...")
    print("   ALLOWED_TELEGRAM_USER_IDS=your_id")
    print("-" * 50)
    print("\n🚀 Setup complete! Run `planner` to start the bot.")


if __name__ == "__main__":
    run_onboarding()

