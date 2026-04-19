"""Tests for the ClaudeAgent.

Uses mocked Anthropic client to test the agentic tool-use loop,
text extraction, max-turn enforcement, and tool error handling —
no real API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from planner_agent.agents.claude_agent import ClaudeAgent
from planner_agent.exceptions import AgentMaxTurnsExceededError
from planner_agent.tools.executor import ToolExecutor
from tests.fakes import FakeSandbox

# ---------------------------------------------------------------------------
# Helpers to build mock Anthropic responses
# ---------------------------------------------------------------------------

@dataclass
class _MockUsage:
    input_tokens: int = 50
    output_tokens: int = 30


@dataclass
class _MockTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class _MockToolUseBlock:
    type: str = "tool_use"
    id: str = "call_1"
    name: str = "read_file"
    input: dict[str, Any] = None

    def __post_init__(self):
        if self.input is None:
            self.input = {}


@dataclass
class _MockResponse:
    content: list = None
    stop_reason: str = "end_turn"
    usage: _MockUsage = None

    def __post_init__(self):
        if self.content is None:
            self.content = [_MockTextBlock(text="Hello!")]
        if self.usage is None:
            self.usage = _MockUsage()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sandbox() -> FakeSandbox:
    return FakeSandbox(files={
        "instructions/system_prompt.md": "You are a planner.",
    })


@pytest.fixture()
def tool_executor(sandbox) -> ToolExecutor:
    return ToolExecutor(sandbox=sandbox, timezone="UTC")


def _make_agent(tool_executor: ToolExecutor, mock_client: AsyncMock, max_turns: int = 10) -> ClaudeAgent:
    """Build a ClaudeAgent wired to a mocked Anthropic client."""
    agent = ClaudeAgent(
        api_key="sk-fake",
        model="claude-test",
        tool_executor=tool_executor,
        max_turns=max_turns,
    )
    agent._client = mock_client
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSimpleResponse:
    """Agent returns text immediately (no tool use)."""

    @pytest.mark.asyncio
    async def test_returns_text(self, tool_executor):
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _MockResponse(
            content=[_MockTextBlock(text="Here's your plan!")],
            stop_reason="end_turn",
        )
        agent = _make_agent(tool_executor, mock_client)

        result = await agent.run("plan my day", [], "system prompt")
        assert result.text == "Here's your plan!"
        assert result.token_usage["input_tokens"] == 50
        assert result.token_usage["output_tokens"] == 30

    @pytest.mark.asyncio
    async def test_empty_text_fallback(self, tool_executor):
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _MockResponse(
            content=[],
            stop_reason="end_turn",
        )
        agent = _make_agent(tool_executor, mock_client)

        result = await agent.run("hi", [], "prompt")
        assert result.text == "(No response text)"


class TestToolUseLoop:
    """Agent makes tool calls before returning text."""

    @pytest.mark.asyncio
    async def test_single_tool_call(self, tool_executor, sandbox):
        mock_client = AsyncMock()

        # First call: tool_use (read_file)
        tool_response = _MockResponse(
            content=[
                _MockToolUseBlock(
                    id="call_1",
                    name="read_file",
                    input={"path": "instructions/system_prompt.md"},
                ),
            ],
            stop_reason="tool_use",
        )
        # Second call: end_turn with text
        text_response = _MockResponse(
            content=[_MockTextBlock(text="Done reading!")],
            stop_reason="end_turn",
        )
        mock_client.messages.create.side_effect = [tool_response, text_response]

        agent = _make_agent(tool_executor, mock_client)
        result = await agent.run("read something", [], "prompt")

        assert result.text == "Done reading!"
        assert "read_file" in result.tool_calls_made
        assert result.token_usage["input_tokens"] == 100  # 50 + 50

    @pytest.mark.asyncio
    async def test_missing_file_sends_helpful_result_to_claude(self, tool_executor):
        mock_client = AsyncMock()

        # Tool call for a missing file — now returns a helpful message, not an error
        tool_response = _MockResponse(
            content=[
                _MockToolUseBlock(
                    id="call_1",
                    name="read_file",
                    input={"path": "nope.txt"},
                ),
            ],
            stop_reason="tool_use",
        )
        text_response = _MockResponse(
            content=[_MockTextBlock(text="I'll create that file for you.")],
            stop_reason="end_turn",
        )
        mock_client.messages.create.side_effect = [tool_response, text_response]

        agent = _make_agent(tool_executor, mock_client)
        result = await agent.run("read nope", [], "prompt")

        assert result.text == "I'll create that file for you."
        # Verify the helpful message was sent back (not an error)
        second_call_args = mock_client.messages.create.call_args_list[1]
        messages = second_call_args.kwargs["messages"]
        tool_result_msg = messages[-1]  # last message should be tool result
        tool_result = tool_result_msg["content"][0]
        assert "does not exist yet" in tool_result["content"]
        assert tool_result.get("is_error") is None


class TestMaxTurns:
    """Agent exceeds maximum tool-use turns."""

    @pytest.mark.asyncio
    async def test_max_turns_exceeded_raises(self, tool_executor):
        mock_client = AsyncMock()

        # Always return tool_use — never end_turn
        infinite_tool = _MockResponse(
            content=[
                _MockToolUseBlock(
                    id="call_inf",
                    name="get_current_datetime",
                    input={},
                ),
            ],
            stop_reason="tool_use",
        )
        mock_client.messages.create.return_value = infinite_tool

        agent = _make_agent(tool_executor, mock_client, max_turns=3)

        with pytest.raises(AgentMaxTurnsExceededError, match="3"):
            await agent.run("loop forever", [], "prompt")

        # Should have called the API exactly 3 times
        assert mock_client.messages.create.call_count == 3

