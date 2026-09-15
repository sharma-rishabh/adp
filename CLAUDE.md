# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
poetry install                              # install deps (Python 3.12+)
poetry run planner                          # run the Telegram bot
poetry run planner-setup                    # interactive onboarding wizard (writes ~/.adp/config.yaml + seeds sandbox)

poetry run pytest                           # all tests
poetry run pytest tests/test_orchestrator.py::test_name   # single test
poetry run ruff check src/ tests/           # lint
poetry run ruff format src/ tests/          # format
```

`asyncio_mode = "auto"` is set, so `async def test_*` needs no `@pytest.mark.asyncio`.

## Coding standards

`AGENT.md` is the authoritative style guide — read it before non-trivial changes. The load-bearing rules: interface-first (depend on the ABC, never the concrete class), constructor dependency injection with **no global state**, and **env vars are read only in `config.py`/entrypoint** — never inside business-logic classes.

## Architecture

A single-user, self-hosted assistant. A Telegram message flows: **adapter → orchestrator → agent (Claude tool-use loop) → tool executor → sandbox**, and back. `main.py` is the only place that reads env, loads config, and instantiates concrete classes — everything else receives injected abstractions.

Layers (each has a `base.py` ABC + concrete impl):
- **`adapters/`** — transport only, no business logic. `TelegramAdapter` gates on an allowlist and translates to/from `IncomingMessage`/`OutgoingMessage` (frozen dataclasses).
- **`orchestrator.py`** — per-user in-memory conversation history, loads the system prompt fresh on every message, records tokens. Intercepts `/clear`, `/skill`, `/pause` slash commands *before* the agent (zero-token path).
- **`agents/`** — `ClaudeAgent` runs the Anthropic tool-use loop until `end_turn` or `max_turns` (raises `AgentMaxTurnsExceededError`).
- **`tools/`** — `definitions.py` is pure tool schemas; `executor.py` is the single dispatch point mapping tool names to sandbox/chart operations.
- **`sandbox/`** — `SandboxFileManager` confines all file I/O under one root; `_resolve_safe` blocks path traversal (`SandboxPathTraversalError`).
- **`heartbeat.py`** — background asyncio loops that inject `[heartbeat-nudge]` / `[eod-reflection]` triggers through the orchestrator. The **agent decides** whether to nudge; returning `[skip]` sends nothing. Respects quiet hours, an explicit `/pause`, and backs off after consecutive ignored nudges.

There is no semantic/vector memory store — MemPalace was removed (see `PLANNED_CHANGES.md` #1). All persistence is plain sandbox files.

### The agent's behavior lives in Markdown, not Python

The assistant's actual product logic is in `sandbox/instructions/*.md` (system prompt + per-task playbooks like `nudge.md`, `eod_reflection.md`, `budget_tracking.md`). These are **bundled templates** copied into the user's sandbox on first run (`seed_sandbox` in `config.py`). The system prompt is re-read on every message, so editing it takes effect immediately with no restart. To change how the assistant behaves, edit the Markdown — not the Python.

### Data conventions (enforced across executor + prompts)

- **Structured, must-read-back data → sandbox files:** `schedule.md` (`## Recurring` preserved, `## Today (YYYY-MM-DD)` overwritten daily), and `budget/YYYY-MM.json` / `habits/<name>.json` as NDJSON.
- **`budget/` and `habits/` JSON must use `append_file`, never `write_file`** — the executor actively refuses `write_file` on non-empty files there to prevent data loss.
- **Action items & goals → `todos.md` / `goals.md`**, read/written in full — no semantic search.
- **Reflections & notes → `journal/YYYY-MM.md`**, one `## YYYY-MM-DD` heading per day, written by the EOD reflection. **Durable preferences → `preferences.md`.** Conversation history is in-memory only now — not archived anywhere, lost on restart.

## Configuration split

Non-secret settings live in a YAML file (default `~/.adp/config.yaml`, override with `ADP_CONFIG_PATH`); secrets (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_IDS`) stay in env/`.env`. First run auto-writes a default config. `AppConfig` is a frozen dataclass built by `from_file()`, which validates and fails fast (`ConfigValidationError`).

## Testing

Tests mirror `src/` and use fakes from `tests/fakes.py` (`FakeAgent`, in-memory sandbox) — **no real API/network calls**. Inject fakes via constructors to exercise orchestration.

## Planned changes (not yet implemented)

See `PLANNED_CHANGES.md` for scoped-but-unbuilt decisions still open: nudge/
reflection wording tweaks, one-tap Telegram inline buttons, and a weekly/
monthly digest (depends on the `journal/` files above). Check it before
touching `heartbeat.py` or the nudge/reflection instruction Markdown — there
may already be a plan for what you're about to change.
