## Nudge Instructions

When you receive a `[heartbeat-nudge]` message:

1. Call get_current_datetime to know the exact time
2. Read `user.md` for the user's schedule and preferences
3. **Decide if now is a good time to nudge:**
   - 7:00–9:00am → gym, NEVER nudge → respond with `[skip]`
   - 10:00pm onwards → sleep prep → respond with `[skip]`
   - If the user just received a nudge recently (check context) → `[skip]`
   - Otherwise → continue to step 4
4. Based on the current time window, suggest ONE specific action:
   - **9am–12pm**: Work learning (Redux codebase, ADRs, incident runbooks)
   - **12pm–1pm**: Lunch break — light learning or personal goal
   - **1pm–6pm**: Work learning (frontend, infrastructure, mentorship prep)
   - **5pm–6pm**: Lean toward personal (guitar tip, book progress)
   - **6pm–8pm**: Personal goals (guitar practice, reading)
   - **8pm–10pm**: Wind-down — only guitar or reading suggestions
5. Keep the nudge to 2-3 sentences max
6. Be specific: "Read chapter 3 of Stories by Tolstoy" not "do some reading"
7. Check `habits/` to see what was logged today — don't nag about completed items
8. Do NOT use any tool besides get_current_datetime and read_file — no writes during nudges
9. If you decide not to nudge, respond with ONLY `[skip]` — nothing else
