"""Heartbeat scheduler — wakes at fixed times and lets the agent decide.

Runs as a background asyncio task.  At each configured nudge time it
sends a lightweight ``[heartbeat-nudge]`` trigger through the
orchestrator.  The **agent** reads the schedule, checks the current
time, and either responds with a nudge or a silent marker (``[skip]``).
If the agent says ``[skip]``, nothing is sent to the user.

Also schedules a nightly ``[eod-reflection]`` trigger at the
configured time (default 22:30).

Each nudge is a **stateless** single-turn call (no conversation
history) to minimise token usage.

A user who ignores several nudges in a row is backed off (no more
nudges, no more tokens spent) until they send a real message; an
explicit ``/pause`` command (handled by the orchestrator) suppresses
both nudges and EOD reflections for a set duration regardless of
backoff state.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from planner_agent.adapters.base import BaseAdapter, IncomingMessage
from planner_agent.exceptions import SandboxFileNotFoundError
from planner_agent.orchestrator import Orchestrator
from planner_agent.sandbox.base import BaseSandbox
from planner_agent.triggers import (
    EOD_ADAPTER,
    EOD_TRIGGER,
    HEARTBEAT_ADAPTER,
    NUDGE_TRIGGER,
    PAUSED_UNTIL_FILE,
    SKIP_MARKER,
)

logger = logging.getLogger(__name__)

_POLL_SECONDS = 60  # how often the fixed-time loops check the wall clock


class Heartbeat:
    """Fixed-time wake-up that lets the agent decide when to nudge.

    Args:
        orchestrator: Routes the nudge trigger through the agent.
        adapter: Delivers proactive messages to the user.
        user_ids: Telegram user IDs to potentially nudge.
        sandbox: Used to read the ``/pause`` state written by the orchestrator.
        nudge_times: HH:MM strings — nudge opportunities fire once per day
            at each of these times. Empty disables nudges.
        nudge_backoff_threshold: Consecutive ignored nudges (delivered but
            no reply before the next one) after which nudging a user stops
            until they send a real message.
        timezone: IANA timezone string for scheduling.
        eod_reflection_time: HH:MM string for the nightly reflection.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        adapter: BaseAdapter,
        user_ids: list[str],
        sandbox: BaseSandbox,
        nudge_times: tuple[str, ...] | list[str] = ("09:00", "13:00", "18:00"),
        nudge_backoff_threshold: int = 3,
        timezone: str = "Asia/Kolkata",
        eod_reflection_time: str = "22:30",
        quiet_hours_start: str = "23:00",
        quiet_hours_end: str = "09:00",
    ) -> None:
        self._orchestrator = orchestrator
        self._adapter = adapter
        self._user_ids = user_ids
        self._sandbox = sandbox
        self._nudge_times = sorted({self._parse_time(t) for t in nudge_times})
        self._backoff_threshold = nudge_backoff_threshold
        self._timezone = timezone
        self._eod_time = self._parse_time(eod_reflection_time)
        self._quiet_start = self._parse_time(quiet_hours_start)
        self._quiet_end = self._parse_time(quiet_hours_end)
        self._task: asyncio.Task | None = None
        self._eod_task: asyncio.Task | None = None
        self._last_nudge_sent: dict[str, datetime | None] = {uid: None for uid in user_ids}
        # Per-user nudge-backoff bookkeeping: consecutive ignored nudges,
        # and the point in time to watch for a reply that clears the streak.
        self._ignored_streak: dict[str, int] = {uid: 0 for uid in user_ids}
        self._watch_since: dict[str, datetime | None] = {uid: None for uid in user_ids}

    @staticmethod
    def _parse_time(time_str: str) -> time:
        """Parse HH:MM string into a time object."""
        parts = time_str.strip().split(":")
        return time(int(parts[0]), int(parts[1]))

    def start(self) -> None:
        """Launch the background nudge and EOD reflection loops."""
        if self._nudge_times:
            self._task = asyncio.create_task(self._nudge_loop(), name="heartbeat")
            logger.info(
                "Heartbeat scheduled at %s %s",
                ", ".join(t.strftime("%H:%M") for t in self._nudge_times),
                self._timezone,
            )
        else:
            logger.info("Heartbeat disabled — no nudge times configured")

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

    def _is_quiet_hours(self) -> bool:
        """Return True if current time is within quiet hours.

        Handles overnight ranges (e.g. 23:00–09:00) and same-day ranges.
        """
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz).time()
        start = self._quiet_start
        end = self._quiet_end

        if start <= end:
            # Same-day range, e.g. 01:00–05:00
            return start <= now < end
        else:
            # Overnight range, e.g. 23:00–09:00
            return now >= start or now < end

    async def _nudge_loop(self) -> None:
        """Fire a nudge opportunity at each configured time, once per day each.

        Polls on a short interval and checks the wall clock rather than
        sleeping until the next target — see ``_eod_loop`` for why (drift
        on suspend, lost on restart).
        """
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz)
        last_fired: dict[time, date] = {
            t: now.date() for t in self._nudge_times if now.time() >= t
        }
        while True:
            await asyncio.sleep(_POLL_SECONDS)
            now = datetime.now(tz=tz)
            for t in self._nudge_times:
                if self._should_fire(now, t, last_fired.get(t)):
                    last_fired[t] = now.date()
                    if self._is_quiet_hours():
                        logger.debug("Quiet hours — skipping scheduled nudge at %s", t)
                    else:
                        await self._check_in()

    async def _eod_loop(self) -> None:
        """Fire the EOD reflection once per day when the wall clock passes it.

        Polls on a short interval and checks the wall clock rather than
        sleeping ~24h at once.  A long ``asyncio.sleep`` drifts badly when
        the machine suspends (the monotonic clock pauses) and is lost on
        restart — that made reflections fire at random times or not at all.
        """
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz)
        # If we start up already past today's EOD time, wait until tomorrow.
        last_fired: date | None = now.date() if now.time() >= self._eod_time else None
        while True:
            await asyncio.sleep(_POLL_SECONDS)
            now = datetime.now(tz=tz)
            if self._should_fire(now, self._eod_time, last_fired):
                last_fired = now.date()
                await self._trigger_reflection()

    @staticmethod
    def _should_fire(now: datetime, target: time, last_fired: date | None) -> bool:
        """True when a fixed-time trigger is due: past the target, not yet fired today."""
        return now.date() != last_fired and now.time() >= target

    def _is_paused(self) -> bool:
        """True while an explicit ``/pause`` (set via the sandbox file) is in effect."""
        try:
            raw = self._sandbox.read_file(PAUSED_UNTIL_FILE).strip()
        except SandboxFileNotFoundError:
            return False
        if not raw:
            return False
        try:
            paused_until = datetime.fromisoformat(raw)
            return datetime.now(UTC) < paused_until
        except (ValueError, TypeError):
            # Malformed content (bad ISO string, or a naive datetime that
            # can't be compared to an aware one) — fail open rather than
            # let a bad write to this file silently kill the loop forever.
            return False

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
        if self._is_paused():
            logger.debug("Paused — skipping EOD reflection")
            return
        now_str = self._now_formatted()
        for user_id in self._user_ids:
            try:
                incoming = IncomingMessage(
                    user_id=user_id,
                    text=f"{EOD_TRIGGER} Current time: {now_str}",
                    adapter_name=EOD_ADAPTER,
                )
                outgoing = await self._orchestrator.handle_message(incoming)

                if SKIP_MARKER in outgoing.text.lower():
                    logger.debug("Agent skipped EOD reflection for user=%s", user_id)
                    continue

                await self._adapter.send_proactive(user_id, outgoing)
                logger.info("EOD reflection sent to user=%s", user_id)
            except Exception:
                logger.exception("EOD reflection failed for user=%s", user_id)

    async def _check_in(self) -> None:
        """Send the nudge trigger to all users; deliver only if agent responds."""
        if self._is_paused():
            logger.debug("Paused — skipping nudge check-in")
            return
        now_str = self._now_formatted()
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz)
        for user_id in self._user_ids:
            try:
                self._update_backoff(user_id)
                if self._ignored_streak.get(user_id, 0) >= self._backoff_threshold:
                    logger.debug(
                        "Backing off nudges for user=%s (%d ignored in a row)",
                        user_id,
                        self._ignored_streak[user_id],
                    )
                    continue

                last = self._last_nudge_sent.get(user_id)
                if last:
                    mins_ago = int((now - last).total_seconds() / 60)
                    last_info = f"Last nudge sent: {mins_ago} minutes ago"
                else:
                    last_info = "Last nudge sent: never (first nudge today)"

                incoming = IncomingMessage(
                    user_id=user_id,
                    text=f"{NUDGE_TRIGGER} Current time: {now_str}. {last_info}",
                    adapter_name=HEARTBEAT_ADAPTER,
                )
                outgoing = await self._orchestrator.handle_message(incoming)

                # Agent returns [skip] when it decides not to nudge
                if SKIP_MARKER in outgoing.text.lower():
                    logger.debug("Agent chose to skip nudge for user=%s", user_id)
                    continue

                self._last_nudge_sent[user_id] = now
                self._watch_since[user_id] = now
                await self._adapter.send_proactive(user_id, outgoing)
                logger.info("Nudge sent to user=%s", user_id)
            except Exception:
                logger.exception("Heartbeat failed for user=%s", user_id)

    def _update_backoff(self, user_id: str) -> None:
        """Resolve the outcome of the last *delivered* nudge before this cycle.

        ``watch_since`` is only set when a nudge is actually delivered (see
        the end of ``_check_in``) — a cycle where the agent chose ``[skip]``
        or backoff itself suppressed the nudge leaves nothing pending here,
        so it doesn't count as "ignored". If the user has replied since the
        last delivery, the streak resets (this is also how backoff lifts).
        Otherwise it grows by one. Either way ``watch_since`` is cleared —
        it's re-armed only by an actual delivery, never by this method —
        so a run of skip cycles can't keep advancing the streak.
        """
        watch_since = self._watch_since.get(user_id)
        if watch_since is None:
            return
        if self._orchestrator.has_replied_since(user_id, watch_since):
            self._ignored_streak[user_id] = 0
        else:
            self._ignored_streak[user_id] = self._ignored_streak.get(user_id, 0) + 1
        self._watch_since[user_id] = None
