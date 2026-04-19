## Habit Tracking Instructions

### JSON format
Each habit file (`habits/<habit-name>.json`) stores:
```json
{
  "metrics": ["pages", "minutes"],
  "entries": [
    {"date": "2026-04-10", "pages": 30, "minutes": 45},
    {"date": "2026-04-11", "pages": 20, "minutes": 30}
  ]
}
```
- `metrics` lists every tracked field name (e.g. `["pages", "minutes"]`).
- Each entry has `date` plus one key per metric.
- Single-metric habits are the same, just with one metric: `{"metrics": ["minutes"], "entries": [{"date": "...", "minutes": 30}]}`

### Logging a habit
1. Get current date via get_current_datetime
2. Read `habits/<habit-name>.json` (create if missing — ask user for metric names first)
3. Append a new entry with `date` and a value for each metric
4. Write the updated JSON back
5. Confirm with the logged values

### Showing a habit graph
1. Read `habits/<habit-name>.json`
2. For **each metric** the user wants (or all if unspecified), call generate_chart separately:
   - `data_json` = map entries to `[{"date": "...", "value": <metric_value>}, ...]`
   - `y_label` = the metric name capitalised (e.g. "Pages", "Minutes")
   - `title` = include the metric name (e.g. "Reading — Pages", "Reading — Minutes")
3. Use "cumulative" for total progress, "bar" for daily values, "line" for trends
4. Each chart image is sent automatically — just add a brief summary
