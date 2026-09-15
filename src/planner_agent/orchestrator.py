"""Orchestrator — routes messages between adapters and the agent.

Maintains per-user conversation history (in-memory for MVP) and loads
the system prompt from the sandbox on each request so that prompt
edits take effect immediately.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from .adapters.base import IncomingMessage, OutgoingMessage
from .agents.base import AgentResponse, BaseAgent
from .exceptions import SandboxFileNotFoundError
from .sandbox.base import BaseSandbox
from .token_tracker import TokenTracker
from .triggers import EOD_ADAPTER, EOD_TRIGGER, HEARTBEAT_ADAPTER, NUDGE_TRIGGER, PAUSED_UNTIL_FILE

logger = logging.getLogger(__name__)

_SKILLS_FILE = "skills.md"
_DEFAULT_HISTORY_LIMIT = 50  # max message pairs kept per user
_REFLECTION_WINDOW = timedelta(minutes=45)  # keep a reflection on its model across follow-ups
_SYNTHETIC_ADAPTERS = (HEARTBEAT_ADAPTER, EOD_ADAPTER)  # not real user activity
# Digit cap keeps `int(...)` construction of the timedelta below its
# internal overflow point; the day cap below then rejects anything
# unreasonably long with the same "usage" message as a malformed input.
_PAUSE_DURATION_RE = re.compile(r"^(\d{1,4})\s*([dhm])$")
_MAX_PAUSE_DURATION = timedelta(days=30)


def _parse_pause_duration(text: str) -> timedelta | None:
    """Parse a duration like '3d', '12h', '90m'; None if malformed or over 30 days."""
    match = _PAUSE_DURATION_RE.match(text.strip().lower())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    duration = {"d": timedelta(days=amount), "h": timedelta(hours=amount), "m": timedelta(minutes=amount)}[unit]
    return duration if duration <= _MAX_PAUSE_DURATION else None


class Orchestrator:
    """Routes incoming messages to the agent and returns replies.

    Responsibilities:
    - Load the system prompt from the sandbox.
    - Maintain per-user conversation history.
    - Trim history to stay within limits.
    - Log token usage for cost awareness.

    Args:
        agent: The AI agent backend to use.
        sandbox: Sandbox for reading the system prompt.
        system_prompt_path: Relative path (within the sandbox) to the
            system prompt file.
        token_tracker: Optional tracker for daily token budget display.
        history_limit: Maximum number of messages (user+assistant)
            retained per user.  Oldest messages are trimmed first.
        reflection_agent: Optional agent used for EOD reflections (and
            their follow-up turns).  When ``None``, all messages use
            ``agent``.
    """

    def __init__(
        self,
        agent: BaseAgent,
        sandbox: BaseSandbox,
        system_prompt_path: str,
        token_tracker: TokenTracker | None = None,
        history_limit: int = _DEFAULT_HISTORY_LIMIT,
        reflection_agent: BaseAgent | None = None,
    ) -> None:
        self._agent = agent
        self._sandbox = sandbox
        self._system_prompt_path = system_prompt_path
        self._token_tracker = token_tracker
        self._history_limit = history_limit
        self._reflection_agent = reflection_agent
        self._conversations: dict[str, list[dict]] = {}
        self._reflection_until: dict[str, datetime] = {}
        self._last_user_activity: dict[str, datetime] = {}

    async def handle_message(self, incoming: IncomingMessage) -> OutgoingMessage:
        """Process an incoming message and return the agent's reply.

        Args:
            incoming: The message received from an adapter.

        Returns:
            An ``OutgoingMessage`` ready for the adapter to send.
        """
        if incoming.adapter_name not in _SYNTHETIC_ADAPTERS:
            self._last_user_activity[incoming.user_id] = incoming.timestamp

        # Handle slash commands that bypass the agent (zero tokens)
        logger.info(f">>> {incoming.text}")
        command_response = self._handle_command(incoming)
        if command_response is not None:
            return command_response

        logger.info(
            "Received message from user=%s via %s",
            incoming.user_id,
            incoming.adapter_name,
        )

        system_prompt = self._load_system_prompt()
        history = self._conversations.get(incoming.user_id, [])

        agent = self._select_agent(incoming)
        response = await agent.run(
            user_message=incoming.text,
            conversation_history=history,
            system_prompt=system_prompt,
        )
        logger.info(f">>>> {response.text}")
        self._update_history(incoming.user_id, incoming.text, response)
        self._log_usage(incoming.user_id, response)

        # Track tokens and build progress bar (not stored in history)
        reply_text = response.text
        if self._token_tracker and response.token_usage:
            self._token_tracker.record(
                response.token_usage.get("input_tokens", 0),
                response.token_usage.get("output_tokens", 0),
            )
            bar = self._token_tracker.progress_bar()
            if bar:
                reply_text = f"{reply_text}\n\n{bar}"

        return OutgoingMessage(
            user_id=incoming.user_id,
            text=reply_text,
            image_paths=response.image_paths,
        )

    def _load_system_prompt(self) -> str:
        """Read the system prompt from the sandbox.

        Returns:
            The system prompt text.
        """
        return self._sandbox.read_file(self._system_prompt_path)

    def _select_agent(self, incoming: IncomingMessage) -> BaseAgent:
        """Choose which agent handles this message.

        EOD reflections run on the reflection agent; nudges and ordinary
        chat run on the primary agent.  A reflection is multi-turn (ask
        questions, then process the user's reply), so once one starts, the
        reflection agent stays selected for follow-up messages within a
        short window — the whole reflection uses the same model, not just
        the opening turn.  Falls back to the primary agent when no
        reflection agent is configured.

        Args:
            incoming: The message being routed.

        Returns:
            The agent that should handle ``incoming``.
        """
        if self._reflection_agent is None:
            return self._agent

        user_id = incoming.user_id
        now = datetime.now(UTC)

        if incoming.text.startswith(EOD_TRIGGER):
            self._reflection_until[user_id] = now + _REFLECTION_WINDOW
            logger.info("Routing reflection to reflection agent for user=%s", user_id)
            return self._reflection_agent
        if incoming.text.startswith(NUDGE_TRIGGER):
            return self._agent  # nudges always use the cheaper primary model
        if now < self._reflection_until.get(user_id, now):
            # Still inside a reflection exchange — keep it on the same model,
            # extending the window across each turn.
            # ponytail: 45-min inactivity window ends the reflection; a reply
            # after a longer gap falls back to the primary model.
            self._reflection_until[user_id] = now + _REFLECTION_WINDOW
            return self._reflection_agent
        return self._agent

    def _update_history(
        self,
        user_id: str,
        user_text: str,
        response: AgentResponse,
    ) -> None:
        """Append the latest exchange and trim if over the limit.

        Args:
            user_id: The user's identifier.
            user_text: The user's message text.
            response: The agent's response.
        """
        history = self._conversations.setdefault(user_id, [])
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response.text})

        if len(history) > self._history_limit:
            overflow = len(history) - self._history_limit

            self._conversations[user_id] = history[overflow:]
            logger.debug(
                "Trimmed %d messages from history for user=%s",
                overflow,
                user_id,
            )

    def _log_usage(self, user_id: str, response: AgentResponse) -> None:
        """Log token usage and tool calls.

        Args:
            user_id: The user's identifier.
            response: The agent's response with usage metadata.
        """
        if response.token_usage:
            logger.info(
                "Token usage for user=%s: input=%d output=%d",
                user_id,
                response.token_usage.get("input_tokens", 0),
                response.token_usage.get("output_tokens", 0),
            )
        if response.tool_calls_made:
            logger.info(
                "Tools called for user=%s: %s",
                user_id,
                ", ".join(response.tool_calls_made),
            )

    def has_replied_since(self, user_id: str, since: datetime) -> bool:
        """Whether the user sent a real (non-heartbeat, non-EOD) message after ``since``.

        Used by the heartbeat's nudge backoff to detect re-engagement.

        Args:
            user_id: The user to check.
            since: The cutoff timestamp.

        Returns:
            True if the user's last real message is after ``since``.
        """
        last = self._last_user_activity.get(user_id)
        return last is not None and last > since

    def clear_history(self, user_id: str) -> None:
        """Clear conversation history for a user.

        Args:
            user_id: The user whose history to clear.
        """
        self._conversations.pop(user_id, None)
        logger.info("Cleared history for user=%s", user_id)

    def _handle_command(self, incoming: IncomingMessage) -> OutgoingMessage | None:
        """Handle slash commands that bypass the agent (zero tokens).

        Args:
            incoming: The incoming message to check.

        Returns:
            An ``OutgoingMessage`` if a command was matched, else ``None``.
        """
        text = incoming.text.strip()

        if text.lower() == "/clear":
            self.clear_history(incoming.user_id)
            return OutgoingMessage(
                user_id=incoming.user_id,
                text="🗑️ Conversation history cleared.",
            )

        if text.lower().startswith("/pause"):
            return self._handle_pause_command(incoming, text)

        if text.lower().startswith("/skill"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return OutgoingMessage(
                    user_id=incoming.user_id,
                    text="Usage: /skill <description>\n\n"
                    "Example:\n/skill Budget Tracking — Track daily "
                    "spending in budget/YYYY-MM.json as NDJSON. "
                    "Categories: food, transport, entertainment.",
                )
            skill_text = parts[1].strip()
            try:
                existing = self._sandbox.read_file(_SKILLS_FILE)
            except SandboxFileNotFoundError:
                existing = "# Skills\n"
            self._sandbox.write_file(_SKILLS_FILE, existing.rstrip("\n") + f"\n- {skill_text}\n")
            reply = f"🧠 Skill stored: {skill_text[:80]}…" if len(skill_text) > 80 else f"🧠 Skill stored: {skill_text}"
            return OutgoingMessage(user_id=incoming.user_id, text=reply)

        return None

    def _handle_pause_command(self, incoming: IncomingMessage, text: str) -> OutgoingMessage:
        """Handle ``/pause [<duration>|off]`` — suppresses nudges and EOD reflection.

        Persisted to a sandbox file (survives restarts) so the heartbeat,
        which has no other link to this command, can check it before firing.

        Args:
            incoming: The originating message (for ``user_id``).
            text: The full command text, e.g. ``"/pause 3d"``.

        Returns:
            A status or confirmation ``OutgoingMessage``.
        """
        parts = text.split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if not arg:
            paused_until = self._read_paused_until()
            if paused_until and paused_until > datetime.now(UTC):
                reply = (
                    f"⏸️ Paused until {paused_until.strftime('%Y-%m-%d %H:%M UTC')}. "
                    "Send /pause off to resume early."
                )
            else:
                reply = "▶️ Not paused. Usage: /pause <e.g. 3d, 12h, 90m> or /pause off"
            return OutgoingMessage(user_id=incoming.user_id, text=reply)

        if arg in ("off", "cancel", "resume"):
            self._sandbox.write_file(PAUSED_UNTIL_FILE, "")
            return OutgoingMessage(
                user_id=incoming.user_id,
                text="▶️ Resumed — nudges and reflections are back on.",
            )

        duration = _parse_pause_duration(arg)
        if duration is None:
            return OutgoingMessage(
                user_id=incoming.user_id,
                text="Usage: /pause <e.g. 3d, 12h, 90m> or /pause off",
            )

        until = datetime.now(UTC) + duration
        self._sandbox.write_file(PAUSED_UNTIL_FILE, until.isoformat())
        return OutgoingMessage(
            user_id=incoming.user_id,
            text=(
                f"⏸️ Paused until {until.strftime('%Y-%m-%d %H:%M UTC')}. "
                "Send /pause off to resume early."
            ),
        )

    def _read_paused_until(self) -> datetime | None:
        """Read the persisted pause expiry, if any.

        Returns None for missing/empty/malformed content, and also for a
        naive (no-tzinfo) timestamp — callers compare against an aware
        ``datetime.now(UTC)``, so a naive value here would raise TypeError
        rather than just reading as "not paused".
        """
        try:
            raw = self._sandbox.read_file(PAUSED_UNTIL_FILE).strip()
        except SandboxFileNotFoundError:
            return None
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

