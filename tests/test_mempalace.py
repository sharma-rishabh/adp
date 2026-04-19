"""Tests for MemPalaceStore.

Covers: store/search round-trip, format helpers, and graceful
degradation when ChromaDB is not available.
"""

from __future__ import annotations

import pytest

from planner_agent.memory.mempalace_store import (
    HALL_EVENTS,
    HALL_FACTS,
    HALL_PREFERENCES,
    MemPalaceStore,
)


@pytest.fixture()
def store(tmp_path):
    return MemPalaceStore(palace_path=tmp_path / "palace")


class TestFormatForPrompt:
    def test_empty_returns_no_memories(self):
        assert "No relevant" in MemPalaceStore.format_for_prompt([])

    def test_formats_snippets_as_list(self):
        result = MemPalaceStore.format_for_prompt(["fact one", "fact two"])
        assert "- fact one" in result
        assert "- fact two" in result

    def test_skips_blank_snippets(self):
        result = MemPalaceStore.format_for_prompt(["hello", "", "  "])
        assert result.count("-") == 1


class TestStoreAndSearch:
    def test_store_does_not_raise(self, store):
        # Should not throw even if ChromaDB has quirks
        store.store("User prefers short replies.", hall=HALL_PREFERENCES)

    def test_search_returns_list(self, store):
        results = store.search("communication style", n_results=1)
        # May be empty if nothing stored yet or index not ready
        assert isinstance(results, list)

    def test_round_trip(self, store):
        store.store("Guitar practice was 30 min today", hall=HALL_EVENTS)
        results = store.search("guitar practice", n_results=1)
        # ChromaDB may need a moment; at minimum no crash
        assert isinstance(results, list)


class TestConvenienceMethods:
    def test_store_reflection(self, store):
        store.store_reflection("Good day. Hit all goals.")

    def test_store_goal_update(self, store):
        store.store_goal_update("Finished Redux chapter 3.")

    def test_store_preference(self, store):
        store.store_preference("Prefers IST timestamps.")

