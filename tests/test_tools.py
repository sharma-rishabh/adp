"""Tests for the ToolExecutor.

Covers: all tools via a FakeSandbox, unknown tool errors,
sandbox exceptions propagated as AgentToolExecutionError,
and chart generation.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from planner_agent.exceptions import AgentToolExecutionError
from planner_agent.tools.executor import ToolExecutor
from tests.fakes import FakeMemPalace, FakeSandbox


@pytest.fixture()
def executor() -> ToolExecutor:
    sandbox = FakeSandbox(files={
        "instructions/system_prompt.md": "You are a planner.",
        "daily/2025-01-15.md": "# Plan",
    })
    return ToolExecutor(sandbox=sandbox, timezone="UTC")


@pytest.fixture()
def chart_executor(tmp_path) -> ToolExecutor:
    """Executor with charts_dir configured for chart generation tests."""
    sandbox = FakeSandbox(files={})
    return ToolExecutor(sandbox=sandbox, timezone="UTC", charts_dir=str(tmp_path))


class TestReadFile:
    def test_read_existing(self, executor):
        result = executor.execute("read_file", {"path": "instructions/system_prompt.md"})
        assert result == "You are a planner."

    def test_read_missing_returns_helpful_message(self, executor):
        result = executor.execute("read_file", {"path": "nope.txt"})
        assert "does not exist yet" in result
        assert "write_file" in result


class TestWriteFile:
    def test_write_creates_file(self, executor):
        result = executor.execute("write_file", {"path": "notes/test.md", "content": "hello"})
        assert "notes/test.md" in result


class TestListFiles:
    def test_list_root(self, executor):
        result = executor.execute("list_files", {"directory": "."})
        files = json.loads(result)
        assert "instructions/system_prompt.md" in files
        assert "daily/2025-01-15.md" in files

    def test_list_default_dir(self, executor):
        result = executor.execute("list_files", {})
        files = json.loads(result)
        assert len(files) >= 2


class TestGetCurrentDatetime:
    def test_returns_datetime_string(self, executor):
        result = executor.execute("get_current_datetime", {})
        # Should contain a date, time, timezone, and day of week
        assert "UTC" in result
        assert "(" in result  # day name in parens


class TestGenerateChart:
    """Tests for the generate_chart tool."""

    _SAMPLE_DATA = json.dumps([
        {"date": "2026-04-10", "value": 30},
        {"date": "2026-04-11", "value": 45},
        {"date": "2026-04-12", "value": 20},
    ])

    def test_bar_chart_returns_confirmation(self, chart_executor):
        result = chart_executor.execute("generate_chart", {
            "chart_type": "bar",
            "title": "Reading Time",
            "data_json": self._SAMPLE_DATA,
        })
        assert "Chart saved" in result

    def test_chart_generates_png_file(self, chart_executor, tmp_path):
        chart_executor.execute("generate_chart", {
            "chart_type": "line",
            "title": "Exercise",
            "data_json": self._SAMPLE_DATA,
        })
        images = chart_executor.collect_images()
        assert len(images) == 1
        assert images[0].endswith(".png")
        assert os.path.isfile(images[0])

    def test_cumulative_chart(self, chart_executor):
        chart_executor.execute("generate_chart", {
            "chart_type": "cumulative",
            "title": "Total Pages Read",
            "data_json": self._SAMPLE_DATA,
        })
        images = chart_executor.collect_images()
        assert len(images) == 1

    def test_collect_images_clears_after_call(self, chart_executor):
        chart_executor.execute("generate_chart", {
            "chart_type": "bar",
            "title": "Test",
            "data_json": self._SAMPLE_DATA,
        })
        assert len(chart_executor.collect_images()) == 1
        assert len(chart_executor.collect_images()) == 0

    def test_y_label_is_accepted(self, chart_executor):
        result = chart_executor.execute("generate_chart", {
            "chart_type": "bar",
            "title": "Reading",
            "data_json": self._SAMPLE_DATA,
            "y_label": "Minutes",
        })
        assert "Chart saved" in result
        assert len(chart_executor.collect_images()) == 1

    def test_y_label_defaults_when_omitted(self, chart_executor):
        """Chart generation works without y_label (defaults to 'Value')."""
        result = chart_executor.execute("generate_chart", {
            "chart_type": "line",
            "title": "Test",
            "data_json": self._SAMPLE_DATA,
        })
        assert "Chart saved" in result

    def test_no_charts_dir_raises(self, executor):
        with pytest.raises(AgentToolExecutionError, match="not configured"):
            executor.execute("generate_chart", {
                "chart_type": "bar",
                "title": "Test",
                "data_json": self._SAMPLE_DATA,
            })

    def test_invalid_chart_type_raises(self, chart_executor):
        with pytest.raises(AgentToolExecutionError, match="Unsupported chart_type"):
            chart_executor.execute("generate_chart", {
                "chart_type": "pie",
                "title": "Test",
                "data_json": self._SAMPLE_DATA,
            })

    def test_empty_data_raises(self, chart_executor):
        with pytest.raises(AgentToolExecutionError, match="empty"):
            chart_executor.execute("generate_chart", {
                "chart_type": "bar",
                "title": "Test",
                "data_json": "[]",
            })

    def test_invalid_json_raises(self, chart_executor):
        with pytest.raises(AgentToolExecutionError, match="Invalid JSON"):
            chart_executor.execute("generate_chart", {
                "chart_type": "bar",
                "title": "Test",
                "data_json": "not json",
            })


class TestUnknownTool:
    def test_unknown_tool_raises(self, executor):
        with pytest.raises(AgentToolExecutionError, match="Unknown tool"):
            executor.execute("delete_everything", {})


class TestScheduleArchival:
    """Tests for archiving old schedule to MemPalace before overwriting."""

    def test_write_schedule_archives_old_to_mempalace(self):
        old_schedule = "## Recurring\n- Gym 7-9am\n\n## Today (2026-04-30)\n- Pairing 10-12"
        sandbox = FakeSandbox(files={"schedule.md": old_schedule})
        mp = FakeMemPalace()
        executor = ToolExecutor(sandbox=sandbox, timezone="UTC", mempalace=mp)

        executor.execute("write_file", {"path": "schedule.md", "content": "## Today (2026-05-01)\n- New day"})

        assert len(mp.stored) == 1
        text, hall, room = mp.stored[0]
        assert "2026-04-30" in text
        assert hall == "hall_events"
        assert room == "schedule-archive"

    def test_write_schedule_without_mempalace_is_safe(self):
        sandbox = FakeSandbox(files={"schedule.md": "old"})
        executor = ToolExecutor(sandbox=sandbox, timezone="UTC", mempalace=None)
        # Should not raise
        executor.execute("write_file", {"path": "schedule.md", "content": "new"})

    def test_write_schedule_no_existing_file_is_safe(self):
        sandbox = FakeSandbox(files={})
        mp = FakeMemPalace()
        executor = ToolExecutor(sandbox=sandbox, timezone="UTC", mempalace=mp)
        executor.execute("write_file", {"path": "schedule.md", "content": "new"})
        # No old file to archive
        assert len(mp.stored) == 0

    def test_write_non_schedule_file_does_not_archive(self):
        sandbox = FakeSandbox(files={"schedule.md": "old schedule"})
        mp = FakeMemPalace()
        executor = ToolExecutor(sandbox=sandbox, timezone="UTC", mempalace=mp)
        executor.execute("write_file", {"path": "notes/test.md", "content": "hello"})
        assert len(mp.stored) == 0

    def test_archive_extracts_date_from_today_header(self):
        sandbox = FakeSandbox(files={"schedule.md": "## Today (2026-04-28)\n- Work"})
        mp = FakeMemPalace()
        executor = ToolExecutor(sandbox=sandbox, timezone="UTC", mempalace=mp)
        executor.execute("write_file", {"path": "schedule.md", "content": "new"})

        text, _, _ = mp.stored[0]
        assert "Schedule 2026-04-28" in text


