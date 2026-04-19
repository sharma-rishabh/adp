"""Tool schemas for the Claude agent's tool-use loop.

Each entry follows the Anthropic tool definition format.  These are
pure data — no logic.  Tool *execution* lives in
:mod:`planner_agent.tools.executor`.
"""

from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the sandbox. Use this to read instructions, "
            "daily plans, reflections, notes, or config."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path within the sandbox "
                        "(e.g. 'instructions/system_prompt.md', 'daily/2025-01-15.md')"
                    ),
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write or overwrite a file in the sandbox. "
            "Use this to create/update any file including instructions, "
            "daily plans, reflections, notes, and config."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the sandbox.",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List all files in a sandbox directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Relative directory path (default: root).",
                    "default": ".",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_current_datetime",
        "description": "Get the current date and time in the user's timezone.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "generate_chart",
        "description": (
            "Generate a PNG chart image from date/value data. "
            "Use this for habit tracking graphs, time-spent visualizations, "
            "and any data the user wants plotted. The image is sent to the user automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "cumulative"],
                    "description": (
                        "Chart style: 'bar' for daily bars, 'line' for trend line, "
                        "'cumulative' for running total."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Chart title (e.g. 'Reading — Last 7 Days').",
                },
                "data_json": {
                    "type": "string",
                    "description": (
                        'JSON array of objects: [{"date": "YYYY-MM-DD", "value": <number>}, ...]. '
                        "value is the metric for that day (minutes, count, etc.)."
                    ),
                },
                "y_label": {
                    "type": "string",
                    "description": (
                        "Label for the Y-axis describing the metric "
                        "(e.g. 'Minutes', 'Pages', 'Count', 'Hours'). Defaults to 'Value'."
                    ),
                },
            },
            "required": ["chart_type", "title", "data_json"],
        },
    },
    {
        "name": "memory_search",
        "description": (
            "Semantic search across past reflections, notes and conversations "
            "stored in MemPalace. Returns the most relevant snippets. "
            "Use instead of reading MEMORY.md for historical context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language query (e.g. 'guitar practice last week').",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Max snippets to return (default 3, keep low for cost).",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_store",
        "description": (
            "Store a memory in MemPalace for future semantic retrieval. "
            "Use for reflections, goal updates, preferences — anything worth remembering. "
            "Do NOT use for ephemeral info (today's schedule, temp notes)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to store verbatim.",
                },
                "category": {
                    "type": "string",
                    "enum": ["reflection", "goal", "preference", "event"],
                    "description": "Memory category for organisation.",
                    "default": "event",
                },
            },
            "required": ["text"],
        },
    },
]

