"""Application entrypoint — wires dependencies and starts the bot.

This is the **only** module that reads environment variables (via
:class:`~planner_agent.config.AppConfig`) and instantiates concrete
implementations.  All other modules depend on injected abstractions.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from .adapters.telegram import TelegramAdapter
from .agents.claude_agent import ClaudeAgent
from .config import AppConfig
from .heartbeat import Heartbeat
from .memory.mempalace_store import MemPalaceStore
from .orchestrator import Orchestrator
from .sandbox.file_manager import SandboxFileManager
from .token_tracker import TokenTracker
from .tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Set up root logger with a readable console format."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


async def  _async_main() -> None:
    """Assemble the application graph and run the Telegram adapter."""
    load_dotenv()
    config = AppConfig.from_env()

    sandbox = SandboxFileManager(sandbox_root=config.sandbox_path)
    charts_dir = str(Path(config.sandbox_path) / "charts")

    mempalace: MemPalaceStore | None = None
    if config.use_mempalace:
        mempalace = MemPalaceStore(palace_path=sandbox.palace_path)
        logger.info("MemPalace enabled at %s", sandbox.palace_path)

    tool_executor = ToolExecutor(
        sandbox=sandbox,
        timezone=config.timezone,
        charts_dir=charts_dir,
        mempalace=mempalace,
    )

    agent = ClaudeAgent(
        api_key=config.anthropic_api_key,
        model=config.claude_model,
        tool_executor=tool_executor,
        max_turns=config.max_agent_turns,
    )

    token_tracker = TokenTracker(
        daily_budget=config.daily_token_budget,
        timezone=config.timezone,
        model=config.claude_model,
    )

    orchestrator = Orchestrator(
        agent=agent,
        sandbox=sandbox,
        system_prompt_path=config.system_prompt_path,
        token_tracker=token_tracker,
        mempalace=mempalace,
    )

    adapter = TelegramAdapter(
        bot_token=config.telegram_bot_token,
        allowed_user_ids=set(config.allowed_user_ids),
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await adapter.start(on_message=orchestrator.handle_message)

    heartbeat = Heartbeat(
        orchestrator=orchestrator,
        adapter=adapter,
        user_ids=config.allowed_user_ids,
        interval_minutes=config.heartbeat_interval_minutes,
    )
    heartbeat.start()

    logger.info("Bot is running. Press Ctrl+C to stop.")
    await stop_event.wait()

    logger.info("Shutting down…")
    await heartbeat.stop()
    await adapter.stop()


def run() -> None:
    """Synchronous entry point for the ``planner`` console script."""
    _configure_logging()
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    run()

