"""Tests for the Orchestrator.

Uses FakeAgent and FakeSandbox to test message routing, conversation
history management, and history trimming — no real API calls.
"""

from __future__ import annotations

import pytest

from planner_agent.adapters.base import IncomingMessage
from planner_agent.orchestrator import Orchestrator
from planner_agent.token_tracker import TokenTracker
from tests.fakes import FakeAgent, FakeMemPalace, FakeSandbox

_SYSTEM_PROMPT = "You are a test planner."


@pytest.fixture()
def fake_sandbox() -> FakeSandbox:
    return FakeSandbox(files={
        "instructions/system_prompt.md": _SYSTEM_PROMPT,
    })


@pytest.fixture()
def fake_agent() -> FakeAgent:
    return FakeAgent(canned_response="Got it!")


@pytest.fixture()
def orchestrator(fake_agent, fake_sandbox) -> Orchestrator:
    return Orchestrator(
        agent=fake_agent,
        sandbox=fake_sandbox,
        system_prompt_path="instructions/system_prompt.md",
        history_limit=6,
    )


def _make_message(text: str, user_id: str = "user1") -> IncomingMessage:
    return IncomingMessage(user_id=user_id, text=text, adapter_name="test")


class TestHandleMessage:
    """Tests for Orchestrator.handle_message."""

    @pytest.mark.asyncio
    async def test_returns_agent_response(self, orchestrator):
        msg = _make_message("hello")
        reply = await orchestrator.handle_message(msg)
        assert reply.text == "Got it!"
        assert reply.user_id == "user1"

    @pytest.mark.asyncio
    async def test_passes_message_to_agent(self, orchestrator, fake_agent):
        msg = _make_message("plan my day")
        await orchestrator.handle_message(msg)
        assert fake_agent.calls == ["plan my day"]

    @pytest.mark.asyncio
    async def test_separate_users_have_separate_histories(self, orchestrator, fake_agent):
        await orchestrator.handle_message(_make_message("hi", user_id="a"))
        await orchestrator.handle_message(_make_message("yo", user_id="b"))
        assert len(orchestrator._conversations["a"]) == 2
        assert len(orchestrator._conversations["b"]) == 2

    @pytest.mark.asyncio
    async def test_conversation_history_accumulates(self, orchestrator):
        await orchestrator.handle_message(_make_message("msg1"))
        await orchestrator.handle_message(_make_message("msg2"))
        history = orchestrator._conversations["user1"]
        # 2 exchanges = 4 messages
        assert len(history) == 4
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "msg1"
        assert history[1]["role"] == "assistant"
        assert history[2]["role"] == "user"
        assert history[2]["content"] == "msg2"


class TestHistoryTrimming:
    """Tests for conversation history limit enforcement."""

    @pytest.mark.asyncio
    async def test_trims_when_over_limit(self, orchestrator):
        # history_limit = 6, each exchange adds 2 messages
        # After 4 exchanges = 8 messages, should trim to 6
        for i in range(4):
            await orchestrator.handle_message(_make_message(f"msg{i}"))

        history = orchestrator._conversations["user1"]
        assert len(history) == 6

    @pytest.mark.asyncio
    async def test_trimmed_history_keeps_latest(self, orchestrator):
        for i in range(4):
            await orchestrator.handle_message(_make_message(f"msg{i}"))

        history = orchestrator._conversations["user1"]
        # Oldest messages trimmed, newest remain
        user_messages = [m["content"] for m in history if m["role"] == "user"]
        assert "msg0" not in user_messages
        assert "msg3" in user_messages


class TestClearHistory:
    """Tests for Orchestrator.clear_history."""

    @pytest.mark.asyncio
    async def test_clear_removes_user_history(self, orchestrator):
        await orchestrator.handle_message(_make_message("hi"))
        assert "user1" in orchestrator._conversations
        orchestrator.clear_history("user1")
        assert "user1" not in orchestrator._conversations

    def test_clear_nonexistent_user_is_safe(self, orchestrator):
        orchestrator.clear_history("nobody")  # should not raise


class TestTokenProgressBar:
    """Tests for progress bar appended to replies."""

    @pytest.fixture()
    def tracked_orchestrator(self, fake_agent, fake_sandbox):
        tracker = TokenTracker(daily_budget=10000, timezone="UTC")
        return Orchestrator(
            agent=fake_agent,
            sandbox=fake_sandbox,
            system_prompt_path="instructions/system_prompt.md",
            token_tracker=tracker,
        )

    @pytest.mark.asyncio
    async def test_progress_bar_appended_to_reply(self, tracked_orchestrator):
        reply = await tracked_orchestrator.handle_message(_make_message("hi"))
        assert "|" in reply.text
        assert "%" in reply.text
        assert "⚡" in reply.text

    @pytest.mark.asyncio
    async def test_progress_bar_not_in_history(self, tracked_orchestrator):
        await tracked_orchestrator.handle_message(_make_message("hi"))
        history = tracked_orchestrator._conversations["user1"]
        assistant_msg = history[1]["content"]
        # History stores raw agent text, not the bar
        assert "⚡" not in assistant_msg
        assert assistant_msg == "Got it!"

    @pytest.mark.asyncio
    async def test_no_tracker_means_no_bar(self, orchestrator):
        reply = await orchestrator.handle_message(_make_message("hi"))
        assert reply.text == "Got it!"
        assert "⚡" not in reply.text


class TestConversationArchival:
    """Tests for archiving trimmed conversations to MemPalace."""

    @pytest.fixture()
    def mempalace(self) -> FakeMemPalace:
        return FakeMemPalace()

    @pytest.fixture()
    def archiving_orchestrator(self, fake_agent, fake_sandbox, mempalace) -> Orchestrator:
        return Orchestrator(
            agent=fake_agent,
            sandbox=fake_sandbox,
            system_prompt_path="instructions/system_prompt.md",
            history_limit=6,
            mempalace=mempalace,
        )

    @pytest.mark.asyncio
    async def test_trimmed_messages_stored_in_mempalace(self, archiving_orchestrator, mempalace):
        # history_limit=6, each exchange=2 messages. After 4 exchanges (8 msgs), trim 2.
        for i in range(4):
            await archiving_orchestrator.handle_message(_make_message(f"msg{i}"))

        assert len(mempalace.stored) == 1
        text, hall, room = mempalace.stored[0]
        assert "conversation-archive" == room
        assert "msg0" in text  # oldest message was archived

    @pytest.mark.asyncio
    async def test_no_archive_when_under_limit(self, archiving_orchestrator, mempalace):
        # 2 exchanges = 4 messages, under limit of 6
        for i in range(2):
            await archiving_orchestrator.handle_message(_make_message(f"msg{i}"))

        assert len(mempalace.stored) == 0

    @pytest.mark.asyncio
    async def test_no_archive_without_mempalace(self, fake_agent, fake_sandbox):
        orch = Orchestrator(
            agent=fake_agent,
            sandbox=fake_sandbox,
            system_prompt_path="instructions/system_prompt.md",
            history_limit=6,
            mempalace=None,
        )
        # Should not raise even when trimming without mempalace
        for i in range(5):
            await orch.handle_message(_make_message(f"msg{i}"))


