## Budget Tracking Instructions

### JSON format
The monthly budget file (`budget/YYYY-MM.json`) stores:
```json
{
  "entries": [
    {"date": "2026-04-10", "item": "coffee", "amount": 150, "category": "food"},
    {"date": "2026-04-10", "item": "uber", "amount": 200, "category": "transport"},
    {"date": "2026-04-11", "item": "groceries", "amount": 1200, "category": "food"}
  ]
}
```
- One file per month: `budget/2026-04.json`, `budget/2026-05.json`, etc.
- Each entry has `date`, `item` (short name), `amount` (number, in ₹), `category`.
- Standard categories: food, transport, entertainment, shopping, health, bills, subscriptions, misc.
- If the user gives a category not in the list, use it as-is — don't force a match.

### Logging spending
1. Get current date via get_current_datetime
2. Read `budget/YYYY-MM.json` (create if missing with `{"entries": []}`)
3. Parse the user's input — accept flexible formats:
   - "coffee 150" → item=coffee, amount=150, category=food (infer)
   - "coffee 150 food" → explicit category
   - "uber 200, lunch 300, book 500" → multiple items
4. Append each as a new entry with today's date
5. Write the updated JSON back
6. Confirm with: items logged + today's running total

### Showing budget summary
When the user asks about spending, budget, or money:
1. Read `budget/YYYY-MM.json` for the requested period (default: current month)
2. Summarise by category with totals
3. If the user asks for a chart, use generate_chart:
   - Group by category for a bar chart
   - Group by date for a line/bar chart of daily spend
   - `data_json` = `[{"date": "<category-or-date>", "value": <total>}, ...]`
   - `y_label` = "₹ Spent"
   - `title` = "Budget — <Month YYYY>" or "Daily Spend — <Month YYYY>"

### Budget goals (optional)
- If the user sets a monthly budget target, store it via memory_store (category: preference)
- When showing summaries, compare against the target and flag if over/under
- During EOD reflection, mention if today's spend pushed past a threshold

