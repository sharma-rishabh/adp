"""Tests for the TokenTracker.

Covers: recording, progress bar formatting, cost estimation, day reset, and edge cases.
"""

from __future__ import annotations

from unittest.mock import patch
from datetime import date, datetime

import pytest

from planner_agent.token_tracker import TokenTracker, _fmt_tokens, _resolve_pricing


class TestRecord:
    def test_accumulates_tokens(self):
        t = TokenTracker(daily_budget=10000, timezone="UTC")
        t.record(100, 50)
        assert t.used == 150
        t.record(200, 100)
        assert t.used == 450

    def test_counts_both_input_and_output(self):
        t = TokenTracker(daily_budget=10000, timezone="UTC")
        t.record(500, 300)
        assert t.used == 800


class TestProgressBar:
    def test_zero_usage(self):
        t = TokenTracker(daily_budget=10000, timezone="UTC")
        bar = t.progress_bar()
        assert "0%" in bar
        assert "░" in bar

    def test_half_usage(self):
        t = TokenTracker(daily_budget=10000, timezone="UTC")
        t.record(3000, 2000)  # 5000 = 50%
        bar = t.progress_bar()
        assert "50%" in bar
        assert "█" in bar

    def test_full_usage(self):
        t = TokenTracker(daily_budget=10000, timezone="UTC")
        t.record(6000, 4000)  # 10000 = 100%
        bar = t.progress_bar()
        assert "100%" in bar

    def test_over_budget_caps_at_100(self):
        t = TokenTracker(daily_budget=1000, timezone="UTC")
        t.record(800, 500)  # 1300 > 1000
        bar = t.progress_bar()
        assert "100%" in bar

    def test_shows_used_and_budget(self):
        t = TokenTracker(daily_budget=100000, timezone="UTC")
        t.record(1200, 300)  # 1500
        bar = t.progress_bar()
        assert "1.5k" in bar
        assert "100.0k" in bar

    def test_shows_cost_estimate(self):
        t = TokenTracker(daily_budget=100000, timezone="UTC", model="claude-3-5-haiku-20241022")
        t.record(10000, 5000)
        bar = t.progress_bar()
        assert "~$" in bar

    def test_zero_budget_returns_empty(self):
        t = TokenTracker(daily_budget=0, timezone="UTC")
        t.record(100, 50)
        assert t.progress_bar() == ""


class TestEstimatedCost:
    def test_haiku_pricing(self):
        t = TokenTracker(daily_budget=100000, timezone="UTC", model="claude-3-5-haiku-20241022")
        t.record(1_000_000, 0)  # 1M input tokens
        assert abs(t.estimated_cost - 0.80) < 0.01

    def test_haiku_output_pricing(self):
        t = TokenTracker(daily_budget=100000, timezone="UTC", model="claude-3-5-haiku-20241022")
        t.record(0, 1_000_000)  # 1M output tokens
        assert abs(t.estimated_cost - 4.00) < 0.01

    def test_mixed_tokens(self):
        t = TokenTracker(daily_budget=100000, timezone="UTC", model="claude-3-5-haiku-20241022")
        t.record(500_000, 100_000)  # 500k in, 100k out
        expected = (500_000 / 1_000_000) * 0.80 + (100_000 / 1_000_000) * 4.00
        assert abs(t.estimated_cost - expected) < 0.001

    def test_unknown_model_uses_default(self):
        t = TokenTracker(daily_budget=100000, timezone="UTC", model="some-future-model")
        t.record(1_000_000, 0)
        assert abs(t.estimated_cost - 1.00) < 0.01  # default $1/MTok input


class TestResolvePricing:
    def test_haiku_35(self):
        assert _resolve_pricing("claude-3-5-haiku-20241022") == (0.80, 4.00)

    def test_sonnet_4(self):
        assert _resolve_pricing("claude-sonnet-4-20250514") == (3.00, 15.00)

    def test_unknown(self):
        assert _resolve_pricing("unknown-model") == (1.00, 5.00)


class TestDayReset:
    def test_resets_on_new_day(self):
        t = TokenTracker(daily_budget=10000, timezone="UTC")
        t.record(5000, 3000)
        assert t.used == 8000

        # Simulate next day
        from datetime import timedelta
        tomorrow = date.today() + timedelta(days=1)
        with patch("planner_agent.token_tracker.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                tomorrow.year, tomorrow.month, tomorrow.day,
                tzinfo=t._tz,
            )
            assert t.used == 0  # triggers reset


class TestFmtTokens:
    def test_small_number(self):
        assert _fmt_tokens(500) == "500"

    def test_thousands(self):
        assert _fmt_tokens(1500) == "1.5k"

    def test_hundred_thousand(self):
        assert _fmt_tokens(100000) == "100.0k"

    def test_millions(self):
        assert _fmt_tokens(1500000) == "1.5M"

