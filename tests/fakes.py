"""Shared test fakes and fixtures.

Provides fake implementations of abstract interfaces so that tests
can exercise orchestration and wiring logic without real API calls.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from planner_agent.agents.base import AgentResponse, BaseAgent
from planner_agent.exceptions import SandboxFileNotFoundError
from planner_agent.sandbox.base import BaseSandbox


class FakeAgent(BaseAgent):
    """In-memory fake agent that returns canned responses.

    Attributes:
        calls: List of user messages received (for assertions).
    """

    def __init__(self, canned_response: str = "fake reply") -> None:
        self.canned_response = canned_response
        self.calls: list[str] = []

    async def run(
        self,
        user_message: str,
        conversation_history: list[dict],
        system_prompt: str,
    ) -> AgentResponse:
        self.calls.append(user_message)
        return AgentResponse(
            text=self.canned_response,
            tool_calls_made=[],
            token_usage={"input_tokens": 10, "output_tokens": 20},
        )


class FakeSandbox(BaseSandbox):
    """In-memory fake sandbox backed by a dict.

    Allows tests to pre-populate files and inspect writes without
    touching the filesystem.

    Attributes:
        files: Dict mapping relative paths to file contents.
    """

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files: dict[str, str] = files or {}

    def read_file(self, relative_path: str) -> str:
        if relative_path not in self.files:
            raise SandboxFileNotFoundError(f"File not found: {relative_path}")
        return self.files[relative_path]

    def write_file(self, relative_path: str, content: str) -> str:
        self.files[relative_path] = content
        return f"Written to {relative_path}"

    def list_files(self, relative_dir: str = ".") -> list[str]:
        prefix = "" if relative_dir == "." else relative_dir.rstrip("/") + "/"
        return sorted(
            path for path in self.files
            if path.startswith(prefix) or relative_dir == "."
        )

    @property
    def palace_path(self) -> Path:
        path = Path(tempfile.mkdtemp()) / "palace"
        path.mkdir(parents=True, exist_ok=True)
        return path


class FakeMemPalace:
    """In-memory fake MemPalace for testing archival logic.

    Attributes:
        stored: List of (text, hall, room) tuples stored.
    """

    def __init__(self) -> None:
        self.stored: list[tuple[str, str, str | None]] = []

    def store(self, text: str, hall: str = "hall_events", room: str | None = None) -> None:
        self.stored.append((text, hall, room))

    def store_schedule(self, schedule_content: str, schedule_date: str | None = None) -> None:
        label = schedule_date or "today"
        self.stored.append((f"[Schedule {label}] {schedule_content}", "hall_events", "schedule-archive"))

    def store_conversation(self, messages: list[dict], user_id: str) -> None:
        if not messages:
            return
        lines = [f"{m['role'].upper()}: {m['content']}" for m in messages]
        text = f"Conversation (user={user_id}):\n" + "\n".join(lines)
        self.stored.append((text, "hall_events", "conversation-archive"))

    def store_reflection(self, summary: str) -> None:
        self.stored.append((summary, "hall_events", "daily-reflection"))

    def store_goal_update(self, note: str) -> None:
        self.stored.append((note, "hall_facts", "goal-progress"))

    def store_preference(self, note: str) -> None:
        self.stored.append((note, "hall_prefs", "habits"))

    def search(self, query: str, n_results: int = 3) -> list[str]:
        return []

    def format_for_prompt(self, snippets: list[str]) -> str:
        return "(No relevant memories found)"

    def format_listing(self, query: str | None = None) -> str:
        return f"🧠 {len(self.stored)} memories"


