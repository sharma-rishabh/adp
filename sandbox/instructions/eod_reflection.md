## EOD Reflection Instructions

When you receive a `[eod-reflection]` trigger OR the user asks for an evening reflection:

### Phase 1 — Gather context (tool calls, no user interaction yet)
1. Call `get_current_datetime` for today's date (YYYY-MM-DD)
2. Call `get_today_schedule` to see what was planned
3. Read `instructions/habit_tracking.md` — follow its format rules for logging habits
4. Read `instructions/budget_tracking.md` — follow its format rules for logging spending
5. Call `memory_search` with "goals long-term objectives" to retrieve user's goals
6. Call `memory_search` with "today reflection progress" for any earlier notes today
7. Call `list_files` on `habits/` then `read_file` for each — check what was logged today
8. Call `read_file` on `budget/YYYY-MM.json` (current month) to see today's spending

### Phase 2 — Ask targeted questions (one message, max 7 questions)
Based on the context above, ask **specific** questions grouped into 3 blocks:

**📋 Schedule & Goals** (2-3 questions):
- Reference actual items from today's schedule: "You had Redux reading blocked 2-4pm — did you get to it?"
- Reference long-term goals: "Any progress on the ADR this week?"

**🏃 Habits** (ask for EACH tracked habit that has no entry today):
- "📖 Reading — how many pages and minutes today?"
- "🎸 Guitar — how many minutes did you practice?"
- "🏋️ Gym — did you go this morning?"
- If a habit already has today's entry, skip it and say "✅ <habit> already logged"

**💰 Budget** (always ask):
- "💰 Any spending today? List like: coffee 150 food, lunch 300 food, uber 200 transport"
- If budget file already has today's entries, show them and ask "Anything else to add?"

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

**Reflection:**
1. Use `memory_store` to save a concise summary:
   - What was accomplished vs planned
   - Goal progress (which long-term goals got attention)
   - What slipped and why
   - Today's total spend and category breakdown
2. Do NOT write reflection .md files — everything goes to MemPalace

### Phase 4 — Summary (one message, concise)
- ✅ What aligned with your goals today
- ⚠️ What slipped or needs attention
- 💰 Today's spend: ₹X total (breakdown by category)
- 🏃 Habits logged: list each with values
- 💡 One specific suggestion for tomorrow
- Keep under 200 tokens

### Rules
- Always ask about budget — this is a daily tracking habit
- Always ask about unlogged habits — check the files first
- If the user says "skip" or "not today", store a minimal reflection and end
- Never ask generic questions like "how was your day" — be specific to schedule and goals
