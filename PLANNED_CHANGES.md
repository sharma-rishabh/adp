# Planned changes

Decisions made 2026-09-11 while diagnosing why the assistant went stale (nudge
pile-up → guilt → abandonment) and why recall felt unreliable.

**Status as of 2026-09-14:** #1, #2, #3, #7, and #8 are implemented (see
below, each marked ✅). #4, #5, #6 are still just specs.

## 1. Remove MemPalace ✅ done

**Why:** the two things it was meant to serve — "what happened on day X" and
"long-term summary of what I've achieved" — are both better served by plain
dated files. Exact-day lookup is a deterministic problem, not a semantic-search
one, and a single user's notes (even 5 years' worth, ~300-500K words) fit in
a model's context window — no vector DB needed until that's no longer true.
It was also actively hurting recall: `search()` in
`src/planner_agent/memory/mempalace_store.py` queries one flat index with no
hall filter, so archived raw conversation turns (stored on *every* exchange,
forever) drown out the sparse high-value facts/preferences in the top-3
results. There's also a dead `where = {"wing": ...}` filter built in that
method and never passed to `search_memories(...)`.

**Replacement:**
- `journal/YYYY-MM.md`, one `## YYYY-MM-DD` section per day, written by the
  EOD reflection instead of `memory_store(category="reflection")`. Exact-day
  recall becomes a plain `read_file` + string match. Long-term summaries
  become "read the last N monthly files and summarize."
- `preferences.md` — durable user preferences, read in full like
  `todos.md`/`goals.md`, instead of `memory_store(category="preference")`.
  Same fix already applied to todos/goals for the same reason (semantic
  recall of small durable facts is unreliable); preferences never got it.

**Implemented:** `src/planner_agent/memory/` deleted entirely.
`config.py`'s `use_mempalace` field, parsing, and `generate_default_config()`
param removed; `seed_sandbox` now seeds `preferences.md` and `skills.md`
alongside `todos.md`/`goals.md`. `main.py`/`orchestrator.py`/`tools/executor.py`
no longer construct or accept a `mempalace` param; `_archive_old_schedule`
and the per-exchange `store_conversation` call in `_update_history` are gone
(conversation history is in-memory only now, not archived anywhere — accepted
loss per the "Why" above). `tools/definitions.py` no longer has
`memory_search`/`memory_store` schemas. `system_prompt.md`, `nudge.md`,
`eod_reflection.md`, `budget_tracking.md` all repointed at `journal/YYYY-MM.md`
and `preferences.md`. `/memories` was dropped (falls through to ordinary
chat); `/skill` now appends to `skills.md` via direct sandbox read/write.
`pyproject.toml`/`poetry.lock` no longer list `mempalace`/`chromadb`.
`scripts/migrate_to_mempalace.py` (the one-time flat-files→MemPalace migration
script, now migrating in the wrong direction) deleted. Tests: `test_mempalace.py`
deleted, `FakeMemPalace` removed from `tests/fakes.py`, and the
MemPalace-dependent tests in `test_orchestrator.py`/`test_tools.py`/
`test_config.py` removed or updated; new coverage added for the repointed
`/skill`, dropped `/memories`, and `preferences.md`/`skills.md` seeding.

**Revisit MemPalace (or something like it) if:** the journal corpus gets too
large to read wholesale for a summary, or a genuine fuzzy/associative recall
need shows up ("did I ever mention wanting to learn Rust") that a dated
journal can't answer because you don't know which day to look in.

## 2. Fixed-time nudges instead of an interval loop ✅ done

**Decision:** 3 fixed nudges/day — **09:00, 13:00, 18:00** — plus the
existing EOD reflection at 22:30 (unchanged, separate mechanism). Replaces
the current "every N minutes, agent decides" loop
(`heartbeat_interval_minutes`, currently 30 in `~/.adp/config.yaml`).

**Why:** predictable, bounded number of daily touches (4 total) that don't
pile up if one gets no reply, vs. an open-ended interval loop that can nudge
repeatedly through a busy day.

**Implemented:** `config.py` has `nudge_times: list[str]` (default
`["09:00", "13:00", "18:00"]`) and `nudge_backoff_threshold: int` (see #3).
`heartbeat.py._nudge_loop` polls every 60s and fires `_check_in()` once per
configured time per day (same drift-resilient pattern as `_eod_loop`, now
shared via the generic `_should_fire(now, target, last_fired)`).
`onboarding.py` collects comma-separated nudge times. The "skip if last
nudge <60min ago" branch in `nudge.md` is still there — harmless dead code
now that nudges are hours apart, left as-is per the original note.

## 3. Heartbeat inactivity backoff ✅ done

**Decision so far:** stop firing nudges (and spending tokens on them) after
some number of consecutive ignored nudges; resume only once the user messages
first. This was the original fix proposed for the pile-up → abandonment
failure mode.

**Decided (2026-09-14, picked without a further user pass — flag if wrong):**
- "Ignored" = a nudge was actually delivered (agent didn't say `[skip]`) and
  the user sent no real message before the *next* scheduled nudge check.
  Evaluated once per outstanding nudge (`Heartbeat._update_backoff`), not
  re-checked every poll tick, so silence isn't double-counted.
- N = 3 consecutive ignored nudges, configurable via
  `nudge_backoff_threshold` in config (same knob pattern as the other
  heartbeat settings).
- "The user messages first" = `Orchestrator.has_replied_since(user_id, t)`,
  backed by `Orchestrator._last_user_activity`, updated in `handle_message`
  for any message whose `adapter_name` isn't the synthetic
  `heartbeat`/`eod-reflection` ones (`triggers.HEARTBEAT_ADAPTER`/`EOD_ADAPTER`).
  Checked at the next scheduled nudge opportunity — not instantaneous, but
  nudges are hours apart so this is a non-issue in practice.
- Backoff only applies to nudges, not the EOD reflection (separate, once-daily,
  higher-value touchpoint — the plan never asked for backoff there).

## 4. Nudge/reflection wording changes (cheap, markdown-only)

- Morning nudge should default to *assuming* yesterday's schedule carries
  over and ask only if it's different, instead of an open "what's on your
  plate today?" — closed-ended prompts get replies more reliably than
  open-ended ones.
- Surface habit streaks in the EOD reflection summary — the data already
  exists in `habits/*.json`, just isn't being surfaced. Visible streaks are a
  cheap, proven accountability lever.
- After any gap in usage, explicit "no catch-up needed" framing on re-entry —
  don't dump a backlog of unlogged days on the user when they come back.

## 5. One-tap replies via Telegram inline buttons

**Why:** typing is the actual friction, not the prompt wording. A tap should
cover the common cases (done / skip) without opening the keyboard.

**Grounded:** `python-telegram-bot>=21` (already a dependency) supports
`InlineKeyboardMarkup`/`InlineKeyboardButton` + `CallbackQueryHandler` — no
new dependency needed.

**Scope:** nudges get `✅ Done` / `⏭ Not now` buttons. Callback taps need to
route back through the system somehow — `adapters/telegram.py` gets a
callback handler, plus a decision on whether a tap:
- goes through the full agent loop (consistent, costs tokens), or
- is handled as a direct zero-token file write (mark the todo/habit done
  immediately), same pattern as the existing slash-command fast path in
  `orchestrator._handle_command`.

**Not yet decided:** exact button set per nudge type; which of the two
routing options above; whether EOD reflection's habit yes/no questions get
buttons too or this starts with nudges only.

## 6. Weekly/monthly digest

**Why:** reinforces the achievement/long-term-summary motivation from the
original idea — proactive evidence of progress instead of only ever asking
for more replies.

**Depends on:** `journal/YYYY-MM.md` from decision #1 — read a week/month of
entries plus `habits/*.json` and `budget/*.json`, summarize.

**Mechanism:** reuse the fixed-time heartbeat scheduling from decision #2,
add one more scheduled slot (e.g. Sunday evening) firing a new
`[weekly-digest]` trigger analogous to `[eod-reflection]`, with its own
`instructions/weekly_digest.md` playbook.

**Not yet decided:** exact day/time, whether it's fixed or configurable.

## 7. Explicit `/pause` or `/snooze` command ✅ done

**Why:** proactive opt-out beats reactive backoff — if you know in advance
you'll be unavailable (travel, crunch week), you tell the bot instead of it
having to notice silence after the fact. Complements decision #3 (backoff is
automatic/reactive; this is manual/proactive) — both can coexist.

**Implemented:** `/pause <duration>` (e.g. `3d`, `12h`, `90m`), `/pause off`
to resume early, and bare `/pause` to check status — handled in
`orchestrator._handle_pause_command` (zero-token path, same as
`/clear`/`/memories`/`/skill`). Persisted as an ISO timestamp in the sandbox
root file `paused_until.txt` (`triggers.PAUSED_UNTIL_FILE`) so it survives
restarts. `Heartbeat._is_paused()` reads that same file; `_check_in` and
`_trigger_reflection` both early-return when paused. Pause is global (one
file, not per-user) — matches the rest of the app's single-shared-sandbox
design even though `allowed_user_ids` can list more than one ID.

## 8. Trim the EOD reflection ✅ done

**Why:** it's currently the single heaviest touchpoint — up to 7 questions in
one message at 10:30pm. That's exactly the kind of thing that gets skipped
once and then feels awkward to resume — plausibly part of what made the whole
system feel stale to restart.

**Implemented (combined all three options):** `eod_reflection.md` now caps
Phase 2 at 4 questions total (1 schedule/goal, at most 2 rotated habits, 1
budget), opens the message with a one-line opt-out ("Quick reflection — N
qs, or reply 'skip' to pass tonight"), and rotates which unlogged habits get
asked about instead of asking every tracked habit every night. Markdown-only
— no code changes needed since the reflection already had a reactive
"skip"/"not today" exit; this just makes that exit cheaper to take (one word
up front instead of reading through the questions first).
