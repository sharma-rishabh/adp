"""Tests for the Heartbeat scheduler.

Covers: start/stop lifecycle, check-in logic, skip filtering, error handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from planner_agent.heartbeat import Heartbeat


class TestHeartbeatLifecycle:
    """Tests for start/stop behaviour."""

    def test_start_with_zero_interval_does_not_create_task(self):
        hb = Heartbeat(
            orchestrator=MagicMock(),
            adapter=MagicMock(),
            user_ids=["123"],
            interval_minutes=0,
        )
        hb.start()
        assert hb._task is None

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
        assert incoming.text == "[heartbeat-nudge]"
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
