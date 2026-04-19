#!/usr/bin/env python3
"""One-time migration: ingest existing sandbox files into MemPalace.

Migrates:
- user.md → hall_preferences (user profile, goals, schedule)
- habits/*.json → hall_events (habit log entries)
- daily/*.md → hall_events (daily plans)
- reflections/*.md → hall_events (reflections)
- notes/*.md → hall_facts (notes)

Skips:
- instructions/** (kept as flat .md files)
- schedule.md (ephemeral, always overwritten)
- palace/** (MemPalace's own data)

Usage:
    poetry run python scripts/migrate_to_mempalace.py [--sandbox PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add src to path so we can import planner_agent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from planner_agent.memory.mempalace_store import (
    HALL_EVENTS,
    HALL_FACTS,
    HALL_PREFERENCES,
    MemPalaceStore,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Directories/files to skip (instructions stay as .md)
SKIP_PREFIXES = ("instructions/", "palace/", "charts/")
SKIP_FILES = ("schedule.md",)

DEFAULT_SANDBOX = Path.home() / ".adp" / "sandbox"


def _migrate_user_profile(store: MemPalaceStore, sandbox: Path, dry_run: bool) -> int:
    """Migrate user.md into hall_preferences as chunked sections."""
    user_file = sandbox / "user.md"
    if not user_file.exists():
        logger.info("No user.md found — skipping profile migration")
        return 0

    text = user_file.read_text(encoding="utf-8").strip()
    if not text:
        return 0

    # Split by ## headings so each section is a separate memory
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())

    count = 0
    for section in sections:
        if len(section) < 10:
            continue
        logger.info("  Profile section: %s…", section[:60])
        if not dry_run:
            store.store(section, hall=HALL_PREFERENCES, room="user-profile")
        count += 1

    return count


def _migrate_habits(store: MemPalaceStore, sandbox: Path, dry_run: bool) -> int:
    """Migrate habits/*.json into hall_events."""
    habits_dir = sandbox / "habits"
    if not habits_dir.is_dir():
        logger.info("No habits/ directory — skipping")
        return 0

    count = 0
    for habit_file in sorted(habits_dir.glob("*.json")):
        habit_name = habit_file.stem
        try:
            raw = habit_file.read_text(encoding="utf-8").strip()
            # Handle both JSON array and newline-delimited JSON
            if raw.startswith("["):
                entries = json.loads(raw)
            else:
                entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("  Skipping %s — bad JSON: %s", habit_file.name, e)
            continue

        for entry in entries:
            date_str = entry.get("date", "unknown")
            value = entry.get("value", "?")
            metric = entry.get("metric", "")
            text = f"[{date_str}] {habit_name}: {value} {metric}".strip()
            logger.info("  Habit: %s", text)
            if not dry_run:
                store.store(text, hall=HALL_EVENTS, room=f"habit-{habit_name}")
            count += 1

    return count


def _migrate_md_dir(
    store: MemPalaceStore,
    sandbox: Path,
    subdir: str,
    hall: str,
    room: str,
    dry_run: bool,
) -> int:
    """Migrate all .md files in a subdirectory."""
    target = sandbox / subdir
    if not target.is_dir():
        logger.info("No %s/ directory — skipping", subdir)
        return 0

    count = 0
    for md_file in sorted(target.glob("*.md")):
        text = md_file.read_text(encoding="utf-8").strip()
        if len(text) < 20:
            continue
        # Prefix with filename (usually date-based)
        label = md_file.stem
        memory = f"[{label}] {text}"
        logger.info("  %s/%s (%d chars)", subdir, md_file.name, len(text))
        if not dry_run:
            store.store(memory, hall=hall, room=room)
        count += 1

    return count


def migrate(sandbox_path: Path, dry_run: bool = False) -> None:
    """Run the full migration."""
    palace_path = sandbox_path / "palace"
    store = MemPalaceStore(palace_path=palace_path)

    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info("=== MemPalace migration (%s) ===", mode)
    logger.info("Sandbox: %s", sandbox_path)
    logger.info("Palace:  %s", palace_path)
    print()

    total = 0

    logger.info("--- Migrating user profile ---")
    total += _migrate_user_profile(store, sandbox_path, dry_run)

    logger.info("--- Migrating habits ---")
    total += _migrate_habits(store, sandbox_path, dry_run)

    logger.info("--- Migrating daily plans ---")
    total += _migrate_md_dir(store, sandbox_path, "daily", HALL_EVENTS, "daily-plan", dry_run)

    logger.info("--- Migrating reflections ---")
    total += _migrate_md_dir(store, sandbox_path, "reflections", HALL_EVENTS, "daily-reflection", dry_run)

    logger.info("--- Migrating notes ---")
    total += _migrate_md_dir(store, sandbox_path, "notes", HALL_FACTS, "notes", dry_run)

    print()
    logger.info("=== Done — %d memories %s ===", total, "would be stored" if dry_run else "stored")

    if not dry_run:
        # Write migration flag so we don't accidentally re-run
        flag = palace_path / ".migrated"
        flag.touch()
        logger.info("Migration flag written to %s", flag)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate sandbox files to MemPalace")
    parser.add_argument(
        "--sandbox",
        type=Path,
        default=DEFAULT_SANDBOX,
        help=f"Path to sandbox root (default: {DEFAULT_SANDBOX})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be migrated without storing anything",
    )
    args = parser.parse_args()

    if not args.sandbox.is_dir():
        logger.error("Sandbox directory not found: %s", args.sandbox)
        sys.exit(1)

    flag = args.sandbox / "palace" / ".migrated"
    if flag.exists() and not args.dry_run:
        logger.warning("Migration already completed (flag at %s). Delete it to re-run.", flag)
        sys.exit(0)

    migrate(args.sandbox, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

