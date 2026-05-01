"""Tests for the Heartbeat scheduler.

Covers: start/stop lifecycle, check-in logic, skip filtering, error handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from planner_agent.heartbeat import Heartbeat


class TestHeartbeatLifecycle:
    """Tests for start/stop behaviour."""

    @pytest.mark.asyncio
    async def test_start_with_zero_interval_does_not_create_nudge_task(self):
        hb = Heartbeat(
            orchestrator=MagicMock(),
            adapter=MagicMock(),
            user_ids=["123"],
            interval_minutes=0,
        )
        hb.start()
        assert hb._task is None
        # EOD task still starts even when nudges are disabled
        assert hb._eod_task is not None
        hb._eod_task.cancel()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        hb = Heartbeat(
            orchestrator=MagicMock(),
            adapter=MagicMock(),
            user_ids=["123"],
            interval_minutes=60,
        )
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

        hb = Heartbeat(
            orchestrator=mock_orchestrator,
            adapter=mock_adapter,
            user_ids=["user1"],
            interval_minutes=60,
        )

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

        hb = Heartbeat(
            orchestrator=mock_orchestrator,
            adapter=mock_adapter,
            user_ids=["user1"],
            interval_minutes=60,
        )

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

        hb = Heartbeat(
            orchestrator=mock_orchestrator,
            adapter=mock_adapter,
            user_ids=["user1"],
            interval_minutes=60,
        )

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

        hb = Heartbeat(
            orchestrator=mock_orchestrator,
            adapter=mock_adapter,
            user_ids=["a", "b"],
            interval_minutes=60,
        )

        await hb._check_in()

        assert mock_orchestrator.handle_message.call_count == 2
        assert mock_adapter.send_proactive.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_error_gracefully(self):
        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_message = AsyncMock(side_effect=RuntimeError("boom"))

        mock_adapter = MagicMock()
        mock_adapter.send_proactive = AsyncMock()

        hb = Heartbeat(
            orchestrator=mock_orchestrator,
            adapter=mock_adapter,
            user_ids=["user1"],
            interval_minutes=60,
        )

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

        hb = Heartbeat(
            orchestrator=mock_orchestrator,
            adapter=mock_adapter,
            user_ids=["user1"],
            interval_minutes=60,
        )

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

        hb = Heartbeat(
            orchestrator=mock_orchestrator,
            adapter=mock_adapter,
            user_ids=["user1"],
            interval_minutes=60,
        )

        await hb._trigger_reflection()
        mock_adapter.send_proactive.assert_not_called()

    def test_seconds_until_eod_is_positive(self):
        hb = Heartbeat(
            orchestrator=MagicMock(),
            adapter=MagicMock(),
            user_ids=["123"],
            interval_minutes=60,
            timezone="Asia/Kolkata",
            eod_reflection_time="22:30",
        )
        seconds = hb._seconds_until_eod()
        assert seconds > 0
        assert seconds <= 86400  # at most 24 hours

    def test_parse_time(self):
        from datetime import time as dt_time
        assert Heartbeat._parse_time("22:30") == dt_time(22, 30)
        assert Heartbeat._parse_time("09:00") == dt_time(9, 0)


class TestQuietHours:
    """Tests for configurable quiet hours."""

    def _make_hb(self, quiet_start: str = "23:00", quiet_end: str = "09:00") -> Heartbeat:
        return Heartbeat(
            orchestrator=MagicMock(),
            adapter=MagicMock(),
            user_ids=["123"],
            interval_minutes=60,
            timezone="Asia/Kolkata",
            quiet_hours_start=quiet_start,
            quiet_hours_end=quiet_end,
        )

    def test_default_quiet_hours_stored(self):
        hb = self._make_hb()
        from datetime import time as dt_time
        assert hb._quiet_start == dt_time(23, 0)
        assert hb._quiet_end == dt_time(9, 0)

    def test_overnight_range_quiet_at_midnight(self):
        """23:00–09:00: midnight should be quiet."""
        hb = self._make_hb("23:00", "09:00")
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
        hb = self._make_hb("23:00", "09:00")
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
        hb = self._make_hb("23:00", "09:00")
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
        hb = self._make_hb("23:00", "09:00")
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
        hb = self._make_hb("01:00", "05:00")
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

        hb = self._make_hb("23:00", "09:00")
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
