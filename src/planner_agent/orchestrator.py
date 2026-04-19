"""Orchestrator — routes messages between adapters and the agent.

Maintains per-user conversation history (in-memory for MVP) and loads
the system prompt from the sandbox on each request so that prompt
edits take effect immediately.
"""

from __future__ import annotations

import logging

from .adapters.base import IncomingMessage, OutgoingMessage
from .agents.base import AgentResponse, BaseAgent
from .memory.mempalace_store import MemPalaceStore
from .sandbox.base import BaseSandbox
from .token_tracker import TokenTracker

logger = logging.getLogger(__name__)

_DEFAULT_HISTORY_LIMIT = 50  # max message pairs kept per user


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
    """

    def __init__(
        self,
        agent: BaseAgent,
        sandbox: BaseSandbox,
        system_prompt_path: str,
        token_tracker: TokenTracker | None = None,
        history_limit: int = _DEFAULT_HISTORY_LIMIT,
        mempalace: MemPalaceStore | None = None,
    ) -> None:
        self._agent = agent
        self._sandbox = sandbox
        self._system_prompt_path = system_prompt_path
        self._token_tracker = token_tracker
        self._history_limit = history_limit
        self._mempalace = mempalace
        self._conversations: dict[str, list[dict]] = {}

    async def handle_message(self, incoming: IncomingMessage) -> OutgoingMessage:
        """Process an incoming message and return the agent's reply.

        Args:
            incoming: The message received from an adapter.

        Returns:
            An ``OutgoingMessage`` ready for the adapter to send.
        """
        # Handle slash commands that bypass the agent (zero tokens)
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

        response = await self._agent.run(
            user_message=incoming.text,
            conversation_history=history,
            system_prompt=system_prompt,
        )

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

        if text.lower().startswith("/memories"):
            if self._mempalace:
                # Extract optional filter: "/memories guitar" → "guitar"
                parts = text.split(maxsplit=1)
                query = parts[1].strip() if len(parts) > 1 else None
                reply = self._mempalace.format_listing(query=query)
            else:
                reply = "MemPalace is disabled (USE_MEMPALACE=false)."
            return OutgoingMessage(user_id=incoming.user_id, text=reply)

        if text.lower() == "/clear":
            self.clear_history(incoming.user_id)
            return OutgoingMessage(
                user_id=incoming.user_id,
                text="🗑️ Conversation history cleared.",
            )

        return None

