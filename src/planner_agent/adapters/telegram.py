"""Telegram adapter using python-telegram-bot (v20+, async).

This adapter translates between Telegram's update model and the
internal :class:`~planner_agent.adapters.base.IncomingMessage` /
:class:`~planner_agent.adapters.base.OutgoingMessage` types.

It contains **no business logic** — only transport and auth gating.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from planner_agent.adapters.base import (
    BaseAdapter,
    IncomingMessage,
    OutgoingMessage,
)
from planner_agent.adapters.base import (
    MessageHandler as OnMessageCallback,
)
from planner_agent.exceptions import AdapterAuthError

logger = logging.getLogger(__name__)

# Telegram has a 4096-char limit per message
_TELEGRAM_MAX_MESSAGE_LENGTH = 4096


class TelegramAdapter(BaseAdapter):
    """Async Telegram bot adapter.

    Only processes messages from users whose IDs are in the
    ``allowed_user_ids`` allowlist.

    Args:
        bot_token: Telegram bot token from BotFather.
        allowed_user_ids: Set of Telegram user IDs permitted to
            interact with the bot.
    """

    def __init__(self, bot_token: str, allowed_user_ids: set[str]) -> None:
        self._bot_token = bot_token
        self._allowed_user_ids = allowed_user_ids
        self._application: Application | None = None
        self._on_message: OnMessageCallback | None = None

    async def start(self, on_message: OnMessageCallback) -> None:
        """Build the Telegram application and start polling.

        Args:
            on_message: Async callback invoked for every authorized
                incoming message.
        """
        self._on_message = on_message

        self._application = (
            Application.builder()
            .token(self._bot_token)
            .build()
        )

        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_update)
        )
        self._application.add_handler(
            CommandHandler(["memories", "clear"], self._handle_update)
        )

        logger.info("Starting Telegram adapter (polling)…")
        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling()

    async def stop(self) -> None:
        """Gracefully shut down the Telegram bot."""
        if self._application and self._application.updater:
            logger.info("Stopping Telegram adapter…")
            await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()

    async def _handle_update(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Process a single Telegram text message.

        Checks authorization, builds an ``IncomingMessage``, calls the
        orchestrator callback, and sends the reply back.

        Args:
            update: The Telegram update object.
            context: The Telegram callback context (unused).
        """
        if not update.message or not update.message.text:
            return

        user_id = str(update.effective_user.id) if update.effective_user else None
        if not user_id:
            return

        if user_id not in self._allowed_user_ids:
            logger.warning("Unauthorized message from user_id=%s", user_id)
            await update.message.reply_text("⛔ You are not authorized to use this bot.")
            return

        incoming = IncomingMessage(
            user_id=user_id,
            text=update.message.text,
            adapter_name="telegram",
        )

        try:
            outgoing = await self._on_message(incoming)
            await self._send_reply(update, outgoing)
        except AdapterAuthError:
            await update.message.reply_text("⛔ Authorization failed.")
        except Exception:
            logger.exception("Error processing message from user=%s", user_id)
            await update.message.reply_text(
                "❌ Something went wrong. Please try again."
            )

    async def send_proactive(self, user_id: str, outgoing: OutgoingMessage) -> None:
        """Send a message to a user without a prior incoming message.

        Args:
            user_id: Telegram chat/user ID.
            outgoing: The message to send.
        """
        if not self._application or not self._application.bot:
            logger.error("Cannot send proactive message — bot not started")
            return

        bot = self._application.bot

        for image_path in outgoing.image_paths:
            try:
                with open(image_path, "rb") as img:
                    await bot.send_photo(chat_id=user_id, photo=img)
            except Exception:
                logger.exception("Failed to send proactive image: %s", image_path)

        for chunk in _split_message(outgoing.text):
            await bot.send_message(chat_id=user_id, text=chunk)

    @staticmethod
    async def _send_reply(update: Update, outgoing: OutgoingMessage) -> None:
        """Send the outgoing message, including images and text.

        Images are sent first as photos, then the text reply follows
        (split into chunks if it exceeds Telegram's limit).

        Args:
            update: The original Telegram update (for reply context).
            outgoing: The message to send.
        """
        for image_path in outgoing.image_paths:
            try:
                with open(image_path, "rb") as img:
                    await update.message.reply_photo(photo=img)
            except Exception:
                logger.exception("Failed to send image: %s", image_path)

        text = outgoing.text
        chunks = _split_message(text)
        for chunk in chunks:
            await update.message.reply_text(chunk)


def _split_message(text: str, max_length: int = _TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a long message into chunks that fit Telegram's limit.

    Splits on newline boundaries when possible to avoid breaking
    mid-sentence.

    Args:
        text: The full message text.
        max_length: Maximum characters per chunk.

    Returns:
        A list of message chunks.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # Try to split at the last newline within the limit
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            # No newline found — hard split
            split_at = max_length

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks

