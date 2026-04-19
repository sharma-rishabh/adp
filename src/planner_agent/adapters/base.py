"""Abstract interface for communication adapters.

Adapters translate between an external messaging system (Telegram,
CLI, Slack, etc.) and the internal message types used by the
orchestrator.  They contain **no business logic** — only transport.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class IncomingMessage:
    """Immutable message received from an external channel.

    Attributes:
        user_id: Unique identifier for the sender.
        text: The message text.
        adapter_name: Name of the adapter that received this message.
        timestamp: UTC timestamp of when the message was received.
        raw: Optional adapter-specific payload for debugging.
    """

    user_id: str
    text: str
    adapter_name: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw: dict | None = None


@dataclass(frozen=True)
class OutgoingMessage:
    """Immutable message to send back through an adapter.

    Attributes:
        user_id: Recipient identifier.
        text: The message text to send.
        image_paths: Optional list of image file paths to attach.
        metadata: Optional adapter-specific metadata.
    """

    user_id: str
    text: str
    image_paths: list[str] = field(default_factory=list)
    metadata: dict | None = None


# Callback type: adapter calls this with each incoming message
MessageHandler = Callable[[IncomingMessage], Awaitable[OutgoingMessage]]


class BaseAdapter(ABC):
    """Abstract base for all communication adapters.

    Implementations must handle connecting to the external service,
    translating messages, and sending replies.
    """

    @abstractmethod
    async def start(self, on_message: MessageHandler) -> None:
        """Start listening for incoming messages.

        This method should block (or run indefinitely) while the
        adapter is active.  For each incoming message, call
        ``on_message`` and send the returned ``OutgoingMessage``.

        Args:
            on_message: Async callback that processes an incoming
                message and returns the outgoing reply.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the adapter."""

    @abstractmethod
    async def send_proactive(self, user_id: str, outgoing: OutgoingMessage) -> None:
        """Push a message to a user without a prior incoming message.

        Used by scheduled tasks like heartbeat nudges.

        Args:
            user_id: The recipient's identifier on this platform.
            outgoing: The message to send.
        """

