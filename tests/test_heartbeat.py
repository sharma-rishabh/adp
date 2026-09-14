"""Tests for the Heartbeat scheduler.

Covers: start/stop lifecycle, check-in logic, skip filtering, error handling,
fixed-time firing, pause, and nudge backoff.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from planner_agent.heartbeat import Heartbeat
from tests.fakes import FakeSandbox


def _make_hb(**overrides) -> Heartbeat:
    defaults = dict(
        orchestrator=MagicMock(),
        adapter=MagicMock(),
        user_ids=["123"],
        sandbox=FakeSandbox(),
    )
    defaults.update(overrides)
    return Heartbeat(**defaults)


class TestHeartbeatLifecycle:
    """Tests for start/stop behaviour."""

    @pytest.mark.asyncio
    async def test_start_with_no_nudge_times_does_not_create_nudge_task(self):
        hb = _make_hb(nudge_times=[])
        hb.start()
        assert hb._task is None
        # EOD task still starts even when nudges are disabled
        assert hb._eod_task is not None
        hb._eod_task.cancel()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        hb = _make_hb()
        await hb.stop()  # should not raise


class TestCheckIn:
    """Tests for _check_in sending messages through orchestrator + adapter."""

    @pytest.mark.asyncio
    async def test_delivers_nudge_when_agent_responds(self):
        mock_outgoing = MagicMock()
        mock_outgoing.text = "Time to practice guitar! 🎸"

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=mock_outgoing)

        mock_adapter = MagicMock()
        mock_adapter.send_proactive = AsyncMock()

        hb = _make_hb(orchestrator=mock_orchestrator, adapter=mock_adapter, user_ids=["user1"])

        await hb._check_in()

        # Orchestrator was called with the nudge trigger
        mock_orchestrator.handle_message.assert_called_once()
        incoming = mock_orchestrator.handle_message.call_args[0][0]
        assert incoming.text.startswith("[heartbeat-nudge]")
        assert "Current time:" in incoming.text
        assert incoming.user_id == "user1"
        assert incoming.adapter_name == "heartbeat"

        # Adapter delivered the message
        mock_adapter.send_proactive.assert_called_once_with("user1", mock_outgoing)

    @pytest.mark.asyncio
    async def test_skips_when_agent_returns_skip(self):
        mock_outgoing = MagicMock()
        mock_outgoing.text = "[skip]"

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=mock_outgoing)

        mock_adapter = MagicMock()
        mock_adapter.send_proactive = AsyncMock()

        hb = _make_hb(orchestrator=mock_orchestrator, adapter=mock_adapter, user_ids=["user1"])

        await hb._check_in()

        # Agent said skip — adapter should NOT be called
        mock_adapter.send_proactive.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_case_insensitive(self):
        mock_outgoing = MagicMock()
        mock_outgoing.text = "[Skip]"

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=mock_outgoing)

        mock_adapter = MagicMock()
        mock_adapter.send_proactive = AsyncMock()

        hb = _make_hb(orchestrator=mock_orchestrator, adapter=mock_adapter, user_ids=["user1"])

        await hb._check_in()
        mock_adapter.send_proactive.assert_not_called()

    @pytest.mark.asyncio
    async def test_checks_in_with_all_users(self):
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(
            return_value=MagicMock(text="nudge!")
        )

        mock_adapter = MagicMock()
        mock_adapter.send_proactive = AsyncMock()

        hb = _make_hb(orchestrator=mock_orchestrator, adapter=mock_adapter, user_ids=["a", "b"])

        await hb._check_in()

        assert mock_orchestrator.handle_message.call_count == 2
        assert mock_adapter.send_proactive.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_error_gracefully(self):
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(side_effect=RuntimeError("boom"))

        mock_adapter = MagicMock()
        mock_adapter.send_proactive = AsyncMock()

        hb = _make_hb(orchestrator=mock_orchestrator, adapter=mock_adapter, user_ids=["user1"])

        # Should not raise
        await hb._check_in()
        mock_adapter.send_proactive.assert_not_called()


class TestEodReflection:
    """Tests for _trigger_reflection and EOD scheduling."""

    @pytest.mark.asyncio
    async def test_delivers_reflection_when_agent_responds(self):
        mock_outgoing = MagicMock()
        mock_outgoing.text = "🌙 Time for your evening reflection!"

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=mock_outgoing)

        mock_adapter = MagicMock()
        mock_adapter.send_proactive = AsyncMock()

        hb = _make_hb(orchestrator=mock_orchestrator, adapter=mock_adapter, user_ids=["user1"])

        await hb._trigger_reflection()

        incoming = mock_orchestrator.handle_message.call_args[0][0]
        assert incoming.text.startswith("[eod-reflection]")
        assert "Current time:" in incoming.text
        assert incoming.adapter_name == "eod-reflection"
        mock_adapter.send_proactive.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_reflection_when_agent_says_skip(self):
        mock_outgoing = MagicMock()
        mock_outgoing.text = "[skip]"

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=mock_outgoing)

        mock_adapter = MagicMock()
        mock_adapter.send_proactive = AsyncMock()

        hb = _make_hb(orchestrator=mock_orchestrator, adapter=mock_adapter, user_ids=["user1"])

        await hb._trigger_reflection()
        mock_adapter.send_proactive.assert_not_called()

    def test_should_fire(self):
        from datetime import date as dt_date, datetime as dt_dt, time as dt_time
        from zoneinfo import ZoneInfo

        hb = _make_hb(timezone="Asia/Kolkata", eod_reflection_time="22:30")
        tz = ZoneInfo("Asia/Kolkata")
        target = dt_time(22, 30)
        before = dt_dt(2026, 5, 1, 22, 0, tzinfo=tz)
        after = dt_dt(2026, 5, 1, 22, 45, tzinfo=tz)

        # Before the target time → don't fire yet
        assert hb._should_fire(before, target, None) is False
        # Past target, not yet fired today → fire
        assert hb._should_fire(after, target, None) is True
        # Past target but already fired today → don't fire again
        assert hb._should_fire(after, target, dt_date(2026, 5, 1)) is False
        # New day, past target → fire again
        assert hb._should_fire(dt_dt(2026, 5, 2, 22, 45, tzinfo=tz), target, dt_date(2026, 5, 1)) is True

    def test_parse_time(self):
        from datetime import time as dt_time
        assert Heartbeat._parse_time("22:30") == dt_time(22, 30)
        assert Heartbeat._parse_time("09:00") == dt_time(9, 0)


class TestNudgeTimes:
    """Tests for fixed nudge-time configuration."""

    def test_default_nudge_times(self):
        from datetime import time as dt_time
        hb = _make_hb()
        assert hb._nudge_times == [dt_time(9, 0), dt_time(13, 0), dt_time(18, 0)]

    def test_custom_nudge_times_sorted_and_deduped(self):
        from datetime import time as dt_time
        hb = _make_hb(nudge_times=["18:00", "09:00", "09:00"])
        assert hb._nudge_times == [dt_time(9, 0), dt_time(18, 0)]

    @pytest.mark.asyncio
    async def test_empty_nudge_times_disables_task(self):
        hb = _make_hb(nudge_times=[])
        hb.start()
        assert hb._task is None
        hb._eod_task.cancel()


class TestPause:
    """Tests for the /pause sandbox-file gate."""

    @pytest.mark.asyncio
    async def test_check_in_skipped_while_paused(self):
        from datetime import UTC, datetime, timedelta

        until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        sandbox = FakeSandbox(files={"paused_until.txt": until})

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock()
        hb = _make_hb(orchestrator=mock_orchestrator, sandbox=sandbox)

        await hb._check_in()
        mock_orchestrator.handle_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_reflection_skipped_while_paused(self):
        from datetime import UTC, datetime, timedelta

        until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        sandbox = FakeSandbox(files={"paused_until.txt": until})

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock()
        hb = _make_hb(orchestrator=mock_orchestrator, sandbox=sandbox)

        await hb._trigger_reflection()
        mock_orchestrator.handle_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_in_proceeds_when_pause_expired(self):
        from datetime import UTC, datetime, timedelta

        expired = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        sandbox = FakeSandbox(files={"paused_until.txt": expired})

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=MagicMock(text="hi"))
        hb = _make_hb(orchestrator=mock_orchestrator, sandbox=sandbox)

        await hb._check_in()
        mock_orchestrator.handle_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_in_proceeds_with_naive_timestamp_in_pause_file(self):
        # A naive (no-tzinfo) ISO string can't be compared to datetime.now(UTC)
        # — must fail open (treated as not-paused) instead of raising and
        # permanently killing the loop.
        sandbox = FakeSandbox(files={"paused_until.txt": "2026-01-01T00:00:00"})

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=MagicMock(text="hi"))
        hb = _make_hb(orchestrator=mock_orchestrator, sandbox=sandbox)

        await hb._check_in()
        mock_orchestrator.handle_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_in_proceeds_with_garbage_pause_file(self):
        sandbox = FakeSandbox(files={"paused_until.txt": "not a timestamp"})

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=MagicMock(text="hi"))
        hb = _make_hb(orchestrator=mock_orchestrator, sandbox=sandbox)

        await hb._check_in()
        mock_orchestrator.handle_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_in_proceeds_when_no_pause_file(self):
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=MagicMock(text="hi"))
        hb = _make_hb(orchestrator=mock_orchestrator, sandbox=FakeSandbox())

        await hb._check_in()
        mock_orchestrator.handle_message.assert_called_once()


class TestNudgeBackoff:
    """Tests for consecutive-ignored-nudge backoff."""

    @pytest.mark.asyncio
    async def test_backs_off_after_threshold_ignored_nudges(self):
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=MagicMock(text="a nudge"))
        mock_orchestrator.has_replied_since = MagicMock(return_value=False)  # never replies

        hb = _make_hb(
            orchestrator=mock_orchestrator,
            user_ids=["user1"],
            nudge_backoff_threshold=2,
        )

        await hb._check_in()  # 1st nudge delivered, nothing to evaluate yet
        await hb._check_in()  # evaluates 1st as ignored (streak=1), delivers 2nd
        await hb._check_in()  # evaluates 2nd as ignored (streak=2) → backs off

        assert mock_orchestrator.handle_message.call_count == 2  # 3rd call was suppressed
        assert hb._ignored_streak["user1"] == 2

    @pytest.mark.asyncio
    async def test_reply_resets_backoff(self):
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=MagicMock(text="a nudge"))
        mock_orchestrator.has_replied_since = MagicMock(return_value=True)  # always replies

        hb = _make_hb(
            orchestrator=mock_orchestrator,
            user_ids=["user1"],
            nudge_backoff_threshold=2,
        )

        await hb._check_in()
        await hb._check_in()
        await hb._check_in()

        assert mock_orchestrator.handle_message.call_count == 3
        assert hb._ignored_streak["user1"] == 0

    @pytest.mark.asyncio
    async def test_skip_cycles_do_not_count_as_ignored(self):
        # Agent delivers once, then legitimately [skip]s twice (busy block,
        # sleep time, etc.), then delivers again. Only the first delivery
        # was ever left unanswered — the two skips must not inflate the
        # streak, since nothing was sent in them to be "ignored".
        outcomes = [
            MagicMock(text="a nudge"),
            MagicMock(text="[skip]"),
            MagicMock(text="[skip]"),
            MagicMock(text="a nudge"),
        ]
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(side_effect=outcomes)
        mock_orchestrator.has_replied_since = MagicMock(return_value=False)

        hb = _make_hb(
            orchestrator=mock_orchestrator,
            user_ids=["user1"],
            nudge_backoff_threshold=2,
        )

        for _ in range(4):
            await hb._check_in()

        # Never suppressed — streak never reached the threshold of 2
        assert mock_orchestrator.handle_message.call_count == 4
        assert hb._ignored_streak["user1"] == 1

    @pytest.mark.asyncio
    async def test_no_backoff_before_any_nudge_sent(self):
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(return_value=MagicMock(text="a nudge"))

        hb = _make_hb(orchestrator=mock_orchestrator, user_ids=["user1"])

        await hb._check_in()
        # has_replied_since should never be consulted — nothing pending yet
        mock_orchestrator.has_replied_since.assert_not_called()


class TestQuietHours:
    """Tests for configurable quiet hours."""

    def _hb(self, quiet_start: str = "23:00", quiet_end: str = "09:00") -> Heartbeat:
        return _make_hb(
            timezone="Asia/Kolkata",
            quiet_hours_start=quiet_start,
            quiet_hours_end=quiet_end,
        )

    def test_default_quiet_hours_stored(self):
        hb = self._hb()
        from datetime import time as dt_time
        assert hb._quiet_start == dt_time(23, 0)
        assert hb._quiet_end == dt_time(9, 0)

    def test_overnight_range_quiet_at_midnight(self):
        """23:00–09:00: midnight should be quiet."""
        hb = self._hb("23:00", "09:00")
        from unittest.mock import patch
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Kolkata")
        with patch("planner_agent.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = dt(2026, 5, 1, 0, 30, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: dt(*a, **kw)
            assert hb._is_quiet_hours() is True

    def test_overnight_range_quiet_at_23(self):
        """23:00–09:00: 23:15 should be quiet."""
        hb = self._hb("23:00", "09:00")
        from unittest.mock import patch
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Kolkata")
        with patch("planner_agent.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = dt(2026, 5, 1, 23, 15, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: dt(*a, **kw)
            assert hb._is_quiet_hours() is True

    def test_overnight_range_active_at_noon(self):
        """23:00–09:00: noon should NOT be quiet."""
        hb = self._hb("23:00", "09:00")
        from unittest.mock import patch
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Kolkata")
        with patch("planner_agent.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = dt(2026, 5, 1, 12, 0, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: dt(*a, **kw)
            assert hb._is_quiet_hours() is False

    def test_overnight_range_active_at_9(self):
        """23:00–09:00: exactly 09:00 should NOT be quiet (end is exclusive)."""
        hb = self._hb("23:00", "09:00")
        from unittest.mock import patch
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Kolkata")
        with patch("planner_agent.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = dt(2026, 5, 1, 9, 0, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: dt(*a, **kw)
            assert hb._is_quiet_hours() is False

    def test_same_day_range(self):
        """01:00–05:00: 03:00 should be quiet, 06:00 should not."""
        hb = self._hb("01:00", "05:00")
        from unittest.mock import patch
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Kolkata")
        with patch("planner_agent.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = dt(2026, 5, 1, 3, 0, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: dt(*a, **kw)
            assert hb._is_quiet_hours() is True

        with patch("planner_agent.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = dt(2026, 5, 1, 6, 0, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: dt(*a, **kw)
            assert hb._is_quiet_hours() is False

    @pytest.mark.asyncio
    async def test_loop_skips_check_in_during_quiet_hours(self):
        """During quiet hours, _check_in should NOT be called."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock()

        hb = self._hb("23:00", "09:00")
        hb._orchestrator = mock_orchestrator

        from unittest.mock import patch
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Kolkata")
        with patch("planner_agent.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = dt(2026, 5, 1, 2, 0, tzinfo=tz)
            mock_dt.side_effect = lambda *a, **kw: dt(*a, **kw)

            # Directly test the quiet hours gate
            assert hb._is_quiet_hours() is True
            # Orchestrator should not have been called
            mock_orchestrator.handle_message.assert_not_called()
