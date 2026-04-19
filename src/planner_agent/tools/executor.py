"""Tool executor — dispatches tool calls to the sandbox or builtins.

This module is the single place where tool names are mapped to actual
operations.  It depends on :class:`~planner_agent.sandbox.base.BaseSandbox`
(the interface, not a concrete implementation).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from planner_agent.exceptions import AgentToolExecutionError, SandboxFileNotFoundError
from planner_agent.memory.mempalace_store import (
    HALL_EVENTS,
    HALL_FACTS,
    HALL_PREFERENCES,
    MemPalaceStore,
)
from planner_agent.sandbox.base import BaseSandbox
from planner_agent.tools.chart import generate_chart

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes agent tool calls against the sandbox.

    Args:
        sandbox: A sandbox implementation for file I/O.
        timezone: IANA timezone string used by ``get_current_datetime``.
        charts_dir: Absolute path where chart PNGs are saved.
    """

    def __init__(
        self,
        sandbox: BaseSandbox,
        timezone: str = "UTC",
        charts_dir: str | None = None,
        mempalace: MemPalaceStore | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._timezone = timezone
        self._charts_dir = charts_dir
        self._mempalace = mempalace
        self._generated_images: list[str] = []

    def collect_images(self) -> list[str]:
        """Return and clear the list of image paths generated since last call."""
        images = self._generated_images.copy()
        self._generated_images.clear()
        return images

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Run a single tool call and return its string result.

        Args:
            tool_name: One of the tool names defined in
                :mod:`~planner_agent.tools.definitions`.
            tool_input: The input payload for the tool.

        Returns:
            A JSON-encoded or plain-text result string.

        Raises:
            AgentToolExecutionError: If the tool name is unknown or
                execution fails for any reason.
        """
        logger.debug("Executing tool=%s input=%s", tool_name, tool_input)
        try:
            if tool_name == "read_file":
                return self._read_file(tool_input)
            if tool_name == "write_file":
                return self._write_file(tool_input)
            if tool_name == "list_files":
                return self._list_files(tool_input)
            if tool_name == "get_current_datetime":
                return self._get_current_datetime()
            if tool_name == "generate_chart":
                return self._generate_chart(tool_input)
            if tool_name == "memory_search":
                return self._memory_search(tool_input)
            if tool_name == "memory_store":
                return self._memory_store(tool_input)
            raise AgentToolExecutionError(f"Unknown tool: {tool_name}")
        except AgentToolExecutionError:
            raise
        except Exception as exc:
            logger.error("Tool '%s' failed: %s", tool_name, exc, exc_info=True)
            raise AgentToolExecutionError(f"Tool '{tool_name}' failed: {exc}") from exc

    def _read_file(self, tool_input: dict[str, Any]) -> str:
        path = tool_input["path"]
        try:
            return self._sandbox.read_file(path)
        except SandboxFileNotFoundError:
            return f"File does not exist yet: {path}. Use write_file to create it."

    def _write_file(self, tool_input: dict[str, Any]) -> str:
        path = tool_input["path"]
        content = tool_input["content"]
        return self._sandbox.write_file(path, content)

    def _list_files(self, tool_input: dict[str, Any]) -> str:
        directory = tool_input.get("directory", ".")
        files = self._sandbox.list_files(directory)
        return json.dumps(files, indent=2)

    def _get_current_datetime(self) -> str:
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")

    def _generate_chart(self, tool_input: dict[str, Any]) -> str:
        if not self._charts_dir:
            raise AgentToolExecutionError("Chart generation is not configured (no charts_dir).")
        path = generate_chart(
            chart_type=tool_input["chart_type"],
            title=tool_input["title"],
            data_json=tool_input["data_json"],
            output_dir=self._charts_dir,
            y_label=tool_input.get("y_label", "Value"),
        )
        self._generated_images.append(path)
        return "Chart saved. It will be sent to you automatically."

    def _memory_search(self, tool_input: dict[str, Any]) -> str:
        if not self._mempalace:
            return "MemPalace is disabled. Use read_file to check sandbox files instead."
        query = tool_input["query"]
        n = tool_input.get("n_results", 3)
        snippets = self._mempalace.search(query, n_results=n)
        if not snippets:
            return "No relevant memories found."
        return json.dumps(snippets, indent=2)

    def _memory_store(self, tool_input: dict[str, Any]) -> str:
        if not self._mempalace:
            return "MemPalace is disabled."
        text = tool_input["text"]
        category = tool_input.get("category", "event")
        category_map = {
            "reflection": self._mempalace.store_reflection,
            "goal": self._mempalace.store_goal_update,
            "preference": self._mempalace.store_preference,
            "event": lambda t: self._mempalace.store(t),
        }
        store_fn = category_map.get(category, category_map["event"])
        store_fn(text)
        return f"Memory stored ({category})."

