"""Claude agent implementation using the Anthropic SDK.

Runs an agentic tool-use loop: sends messages to Claude, executes any
requested tool calls via :class:`~planner_agent.tools.executor.ToolExecutor`,
feeds results back, and repeats until Claude produces a final text
response or the turn limit is reached.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from planner_agent.agents.base import AgentResponse, BaseAgent
from planner_agent.exceptions import AgentMaxTurnsExceededError
from planner_agent.tools.definitions import TOOLS
from planner_agent.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


class ClaudeAgent(BaseAgent):
    """Agent backed by Anthropic Claude with tool-use support.

    Args:
        api_key: Anthropic API key.
        model: Model identifier (e.g. ``claude-3-5-haiku-latest``).
        tool_executor: Executor that handles sandbox tool calls.
        max_turns: Maximum tool-use round-trips per request.
        max_tokens: Maximum tokens per Claude API call.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        tool_executor: ToolExecutor,
        max_turns: int = 10,
        max_tokens: int = 4096,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._tool_executor = tool_executor
        self._max_turns = max_turns
        self._max_tokens = max_tokens

    async def run(
        self,
        user_message: str,
        conversation_history: list[dict],
        system_prompt: str,
    ) -> AgentResponse:
        """Process a user message through Claude's agentic loop.

        Args:
            user_message: The latest message from the user.
            conversation_history: Prior messages in Anthropic format.
            system_prompt: The system prompt to use.

        Returns:
            An ``AgentResponse`` with the final text and token usage.

        Raises:
            AgentMaxTurnsExceededError: If the tool-use loop exceeds
                ``max_turns`` without producing a final response.
        """
        messages: list[dict[str, Any]] = [
            *conversation_history,
            {"role": "user", "content": user_message},
        ]
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        tool_calls_made: list[str] = []

        for turn in range(self._max_turns):
            logger.debug("Agent turn %d/%d", turn + 1, self._max_turns)

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )

            total_usage["input_tokens"] += response.usage.input_tokens
            total_usage["output_tokens"] += response.usage.output_tokens

            if response.stop_reason == "end_turn":
                text = _extract_text(response)
                images = self._tool_executor.collect_images()
                logger.info(
                    "Agent finished in %d turn(s) — tokens in=%d out=%d",
                    turn + 1,
                    total_usage["input_tokens"],
                    total_usage["output_tokens"],
                )
                return AgentResponse(
                    text=text,
                    tool_calls_made=tool_calls_made,
                    token_usage=total_usage,
                    image_paths=images,
                )

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = self._execute_tool_calls(response, tool_calls_made)
                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — extract whatever text is there
            logger.warning("Unexpected stop_reason=%s", response.stop_reason)
            return AgentResponse(
                text=_extract_text(response),
                tool_calls_made=tool_calls_made,
                token_usage=total_usage,
            )

        logger.error("Agent exceeded max turns (%d)", self._max_turns)
        raise AgentMaxTurnsExceededError(
            f"Agent exceeded the maximum of {self._max_turns} tool-use turns."
        )

    def _execute_tool_calls(
        self,
        response: anthropic.types.Message,
        tool_calls_made: list[str],
    ) -> list[dict[str, Any]]:
        """Execute all tool-use blocks in a response.

        Args:
            response: The Claude API response containing tool calls.
            tool_calls_made: Accumulator list; tool names are appended.

        Returns:
            A list of tool-result dicts ready for the next API call.
        """
        results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls_made.append(block.name)
            logger.debug("Calling tool=%s id=%s", block.name, block.id)
            try:
                result = self._tool_executor.execute(block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            except Exception as exc:
                logger.error("Tool %s failed: %s", block.name, exc)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {exc}",
                    "is_error": True,
                })
        return results


def _extract_text(response: anthropic.types.Message) -> str:
    """Extract concatenated text from a Claude response.

    Args:
        response: The Claude API message response.

    Returns:
        All text blocks joined by newlines, or a fallback message.
    """
    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts) if parts else "(No response text)"

