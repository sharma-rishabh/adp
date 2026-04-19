"""Heartbeat scheduler — wakes periodically and lets the agent decide.

Runs as a background asyncio task.  Every *interval* minutes it sends
a lightweight ``[heartbeat-nudge]`` trigger through the orchestrator.
The **agent** reads ``user.md``, checks the current time, and either
responds with a nudge or a silent marker (``[skip]``).  If the agent
says ``[skip]``, nothing is sent to the user.

Each nudge is a **stateless** single-turn call (no conversation
history) to minimise token usage.
"""

from __future__ import annotations

import asyncio
import logging

from planner_agent.adapters.base import BaseAdapter, IncomingMessage
from planner_agent.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

_NUDGE_TRIGGER = "[heartbeat-nudge]"
_SKIP_MARKER = "[skip]"
_DEFAULT_INTERVAL_MINUTES = 60


class Heartbeat:
    """Periodic wake-up that lets the agent decide when to nudge.

    Args:
        orchestrator: Routes the nudge trigger through the agent.
        adapter: Delivers proactive messages to the user.
        user_ids: Telegram user IDs to potentially nudge.
        interval_minutes: Minutes between each wake-up.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        adapter: BaseAdapter,
        user_ids: list[str],
        interval_minutes: int = _DEFAULT_INTERVAL_MINUTES,
    ) -> None:
        self._orchestrator = orchestrator
        self._adapter = adapter
        self._user_ids = user_ids
        self._interval = interval_minutes * 60  # seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Launch the background heartbeat loop."""
        if self._interval <= 0:
            logger.info("Heartbeat disabled — interval is 0")
            return
        self._task = asyncio.create_task(self._loop(), name="heartbeat")
        logger.info(
            "Heartbeat started — waking every %d minutes",
            self._interval // 60,
        )

    async def stop(self) -> None:
        """Cancel the background task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Heartbeat stopped")

    async def _loop(self) -> None:
        """Sleep for the interval, then check in with the agent."""
        while True:
            await asyncio.sleep(self._interval)
            await self._check_in()

    async def _check_in(self) -> None:
        """Send the nudge trigger to all users; deliver only if agent responds."""
        for user_id in self._user_ids:
            try:
                incoming = IncomingMessage(
                    user_id=user_id,
                    text=_NUDGE_TRIGGER,
                    adapter_name="heartbeat",
                )
                outgoing = await self._orchestrator.handle_message(incoming)

                # Agent returns [skip] when it decides not to nudge
                if _SKIP_MARKER in outgoing.text.lower():
                    logger.debug("Agent chose to skip nudge for user=%s", user_id)
                    continue

                await self._adapter.send_proactive(user_id, outgoing)
                logger.info("Nudge sent to user=%s", user_id)
            except Exception:
                logger.exception("Heartbeat failed for user=%s", user_id)
