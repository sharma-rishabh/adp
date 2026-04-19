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

