## EOD Reflection Instructions

When you receive a `[eod-reflection]` trigger OR the user asks for an evening reflection:

### Phase 1 — Gather context (tool calls, no user interaction yet)
1. Call `get_current_datetime` for today's date (YYYY-MM-DD)
2. Call `get_today_schedule` to see what was planned
3. Read `instructions/habit_tracking.md` — follow its format rules for logging habits
4. Read `instructions/budget_tracking.md` — follow its format rules for logging spending
5. Call `read_file` on `goals.md` (long-term goals), `todos.md` (open action items), and `preferences.md`
6. Call `read_file` on this month's `journal/YYYY-MM.md` — check if today's `## YYYY-MM-DD` heading already has notes from earlier
7. Call `list_files` on `habits/` then `read_file` for each — check what was logged today
8. Call `read_file` on `budget/YYYY-MM.json` (current month) to see today's spending

### Phase 2 — Ask targeted questions (one message, max 4 questions total)

Start the message with a one-line opt-out so skipping costs one word, not a
read-through: **"Quick reflection — N qs, or reply 'skip' to pass tonight."**

Then ask **specific** questions, picking at most 4 across these blocks
(priority order — drop lower-priority ones once you hit 4):

1. **📋 Schedule/goal** (1 question) — reference an actual item: "You had
   Redux reading blocked 2-4pm — did you get to it?" or a long-term goal:
   "Any progress on the ADR this week?", or an open `todos.md` item.
2. **🏃 Habits** (at most 2 questions) — pick the 2 tracked habits with no
   entry today that have gone longest without a logged entry (check each
   habit file's last date). Don't ask about every unlogged habit every
   night — rotate. If a habit already has today's entry, skip it silently.
3. **💰 Budget** (1 question, always included if there's room) — "Any
   spending today? List like: coffee 150 food, lunch 300 food, uber 200
   transport." If already logged today, show it and ask "Anything else?"

Number all questions. Wait for the user's reply.

### Phase 3 — Process the user's answers

**Habits:**
1. For each habit the user reports, read `habits/<habit-name>.json`
2. If the file doesn't exist, create it with `{"metrics": [...], "entries": []}`
3. Append today's entry: `{"date": "YYYY-MM-DD", "<metric>": <value>, ...}`
4. Write the updated JSON back

**Budget:**
1. Read `budget/YYYY-MM.json` (create if missing as `{"entries": []}`)
2. Parse spending items from the user's reply
3. Append each as: `{"date": "YYYY-MM-DD", "item": "coffee", "amount": 150, "category": "food"}`
4. Write the updated JSON back
5. Calculate and mention today's total spend

**TODOs & goals:**
1. Read `todos.md`. Flip items the user completed to `- [x] … (done YYYY-MM-DD)`; leave the rest open. Write it back.
2. If the user reports progress on a long-term goal, refine the matching line in `goals.md`.

**Reflection:**
1. Read this month's `journal/YYYY-MM.md` (create with `# Journal` if missing)
2. Append or update today's `## YYYY-MM-DD` heading with a concise summary:
   - What was accomplished vs planned
   - Goal progress (which long-term goals got attention)
   - What slipped and why
   - Today's total spend and category breakdown
3. If today's heading already had notes from Phase 1 step 6, merge rather than duplicate
4. Write the file back

### Phase 4 — Summary (one message, concise)
- ✅ What aligned with your goals today
- ⚠️ What slipped or needs attention
- 💰 Today's spend: ₹X total (breakdown by category)
- 🏃 Habits logged: list each with values
- 📋 TODOs: how many done today, how many still open
- 💡 One specific suggestion for tomorrow
- Keep under 200 tokens

### Rules
- Cap every reflection message at 4 questions total, opt-out line included — this is the whole point of the cap, don't quietly go over
- Rotate habit questions (at most 2/night) instead of asking about every tracked habit every time
- Reconcile `todos.md` every reflection — mark done items, carry the rest forward
- If the user says "skip" or "not today" — including replying to the opening opt-out line — store a minimal reflection and end immediately, no further questions
- Never ask generic questions like "how was your day" — be specific to schedule and goals
