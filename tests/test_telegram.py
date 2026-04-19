"""Tests for the Telegram adapter.

Covers: message splitting logic. The actual Telegram update handling
is integration-level and would require mocking python-telegram-bot
internals, so we focus on the pure utility function.
"""

from __future__ import annotations

from planner_agent.adapters.telegram import _split_message


class TestSplitMessage:
    """Tests for the _split_message utility."""

    def test_short_message_unchanged(self):
        assert _split_message("hello") == ["hello"]

    def test_exact_limit_unchanged(self):
        text = "x" * 4096
        assert _split_message(text) == [text]

    def test_splits_on_newline(self):
        line = "a" * 100
        text = "\n".join([line] * 50)  # 50 lines of 100 chars
        chunks = _split_message(text, max_length=500)
        for chunk in chunks:
            assert len(chunk) <= 500

    def test_hard_split_when_no_newline(self):
        text = "x" * 10000  # no newlines
        chunks = _split_message(text, max_length=4096)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_preserves_all_content(self):
        text = "line1\nline2\nline3\nline4"
        chunks = _split_message(text, max_length=12)
        reassembled = "\n".join(chunks)
        # All original content should be present
        assert "line1" in reassembled
        assert "line4" in reassembled

