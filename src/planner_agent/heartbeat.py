"""Heartbeat scheduler — wakes periodically and lets the agent decide.

Runs as a background asyncio task.  Every *interval* minutes it sends
a lightweight ``[heartbeat-nudge]`` trigger through the orchestrator.
The **agent** reads ``user.md``, checks the current time, and either
responds with a nudge or a silent marker (``[skip]``).  If the agent
says ``[skip]``, nothing is sent to the user.

Also schedules a nightly ``[eod-reflection]`` trigger at the
configured time (default 22:30).

Each nudge is a **stateless** single-turn call (no conversation
history) to minimise token usage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from planner_agent.adapters.base import BaseAdapter, IncomingMessage
from planner_agent.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

_NUDGE_TRIGGER = "[heartbeat-nudge]"
_EOD_TRIGGER = "[eod-reflection]"
_SKIP_MARKER = "[skip]"
_DEFAULT_INTERVAL_MINUTES = 60


class Heartbeat:
    """Periodic wake-up that lets the agent decide when to nudge.

    Args:
        orchestrator: Routes the nudge trigger through the agent.
        adapter: Delivers proactive messages to the user.
        user_ids: Telegram user IDs to potentially nudge.
        interval_minutes: Minutes between each wake-up.
        timezone: IANA timezone string for scheduling EOD reflection.
        eod_reflection_time: HH:MM string for the nightly reflection.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        adapter: BaseAdapter,
        user_ids: list[str],
        interval_minutes: int = _DEFAULT_INTERVAL_MINUTES,
        timezone: str = "Asia/Kolkata",
        eod_reflection_time: str = "22:30",
    ) -> None:
        self._orchestrator = orchestrator
        self._adapter = adapter
        self._user_ids = user_ids
        self._interval = interval_minutes * 60  # seconds
        self._timezone = timezone
        self._eod_time = self._parse_time(eod_reflection_time)
        self._task: asyncio.Task | None = None
        self._eod_task: asyncio.Task | None = None
        self._last_nudge_sent: dict[str, datetime | None] = {uid: None for uid in user_ids}

    @staticmethod
    def _parse_time(time_str: str) -> time:
        """Parse HH:MM string into a time object."""
        parts = time_str.strip().split(":")
        return time(int(parts[0]), int(parts[1]))

    def start(self) -> None:
        """Launch the background heartbeat and EOD reflection loops."""
        if self._interval > 0:
            self._task = asyncio.create_task(self._loop(), name="heartbeat")
            logger.info(
                "Heartbeat started — waking every %d minutes",
                self._interval // 60,
            )
        else:
            logger.info("Heartbeat disabled — interval is 0")

        self._eod_task = asyncio.create_task(
            self._eod_loop(), name="eod-reflection"
        )
        logger.info(
            "EOD reflection scheduled at %s %s",
            self._eod_time.strftime("%H:%M"),
            self._timezone,
        )

    async def stop(self) -> None:
        """Cancel the background tasks."""
        for task in (self._task, self._eod_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("Heartbeat stopped")

    async def _loop(self) -> None:
        """Sleep for the interval, then check in with the agent."""
        while True:
            await asyncio.sleep(self._interval)
            await self._check_in()

    async def _eod_loop(self) -> None:
        """Sleep until the configured EOD time, trigger reflection, repeat daily."""
        while True:
            sleep_seconds = self._seconds_until_eod()
            logger.debug(
                "EOD reflection sleeping for %d seconds", sleep_seconds
            )
            await asyncio.sleep(sleep_seconds)
            await self._trigger_reflection()

    def _seconds_until_eod(self) -> float:
        """Calculate seconds from now until the next EOD reflection time."""
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz)
        target = now.replace(
            hour=self._eod_time.hour,
            minute=self._eod_time.minute,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    def _now_formatted(self) -> str:
        """Return current time in user's timezone as a readable string."""
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz)
        return (
            f"{now.strftime('%Y-%m-%d (%A)')} "
            f"{now.strftime('%I:%M %p')} {self._timezone}"
        )

    async def _trigger_reflection(self) -> None:
        """Send the EOD reflection trigger to all users."""
        now_str = self._now_formatted()
        for user_id in self._user_ids:
            try:
                incoming = IncomingMessage(
                    user_id=user_id,
                    text=f"{_EOD_TRIGGER} Current time: {now_str}",
                    adapter_name="eod-reflection",
                )
                outgoing = await self._orchestrator.handle_message(incoming)

                if _SKIP_MARKER in outgoing.text.lower():
                    logger.debug("Agent skipped EOD reflection for user=%s", user_id)
                    continue

                await self._adapter.send_proactive(user_id, outgoing)
                logger.info("EOD reflection sent to user=%s", user_id)
            except Exception:
                logger.exception("EOD reflection failed for user=%s", user_id)

    async def _check_in(self) -> None:
        """Send the nudge trigger to all users; deliver only if agent responds."""
        now_str = self._now_formatted()
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz)
        for user_id in self._user_ids:
            try:
                last = self._last_nudge_sent.get(user_id)
                if last:
                    mins_ago = int((now - last).total_seconds() / 60)
                    last_info = f"Last nudge sent: {mins_ago} minutes ago"
                else:
                    last_info = "Last nudge sent: never (first nudge today)"

                incoming = IncomingMessage(
                    user_id=user_id,
                    text=f"{_NUDGE_TRIGGER} Current time: {now_str}. {last_info}",
                    adapter_name="heartbeat",
                )
                outgoing = await self._orchestrator.handle_message(incoming)

                # Agent returns [skip] when it decides not to nudge
                if _SKIP_MARKER in outgoing.text.lower():
                    logger.debug("Agent chose to skip nudge for user=%s", user_id)
                    continue

                self._last_nudge_sent[user_id] = now
                await self._adapter.send_proactive(user_id, outgoing)
                logger.info("Nudge sent to user=%s", user_id)
            except Exception:
                logger.exception("Heartbeat failed for user=%s", user_id)
