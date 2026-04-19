"""Abstract interface for AI agent backends.

Every agent implementation must subclass :class:`BaseAgent` and
implement the :meth:`run` method.  The orchestrator depends only
on this interface, never on a concrete agent class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentResponse:
    """Immutable response returned by an agent after processing a message.

    Attributes:
        text: The agent's final textual reply to the user.
        tool_calls_made: Names of tools invoked during the agentic loop.
        token_usage: Token counts keyed by ``input_tokens`` and
            ``output_tokens`` for cost tracking.
        image_paths: Filesystem paths to images generated during the run.
    """

    text: str
    tool_calls_made: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    image_paths: list[str] = field(default_factory=list)


class BaseAgent(ABC):
    """Abstract base for all AI agent backends.

    Implementations are responsible for:
    1. Sending messages to the AI provider.
    2. Handling tool-use loops (call tools, feed results back).
    3. Tracking token usage.
    """

    @abstractmethod
    async def run(
        self,
        user_message: str,
        conversation_history: list[dict],
        system_prompt: str,
    ) -> AgentResponse:
        """Process a user message with full conversation history.

        The agent may invoke tools in an agentic loop before
        producing a final text response.

        Args:
            user_message: The latest message from the user.
            conversation_history: Prior messages in Anthropic
                ``messages`` format.
            system_prompt: The system prompt to use.

        Returns:
            An :class:`AgentResponse` with the text reply and metadata.
        """

