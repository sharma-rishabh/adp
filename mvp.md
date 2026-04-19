

# MVP Document: Personal Agentic Day Planner / Assistant

## Project Overview

A self-hosted agentic day planner and assistant with a sandboxed file environment, Telegram interface, and Claude as the AI backend. The architecture prioritizes extensibility via adapters for both communication channels and AI providers.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Adapters Layer                    │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────┐  │
│  │   Telegram    │  │  CLI     │  │  Future:     │  │
│  │   Adapter     │  │  Adapter │  │  Slack/Web   │  │
│  └──────┬───────┘  └────┬─────┘  └──────┬───────┘  │
│         └───────────┬────┘───────────────┘          │
│                     ▼                                │
│         ┌───────────────────────┐                   │
│         │   Message Router /    │                   │
│         │   Orchestrator        │                   │
│         └───────────┬───────────┘                   │
│                     ▼                                │
│         ┌───────────────────────┐                   │
│         │   Agent Layer         │                   │
│  ┌──────┴───────┐  ┌───────────┴────┐              │
│  │ Claude Agent  │  │ Future: OpenAI │              │
│  └──────┬───────┘  └────────────────┘              │
│         ▼                                           │
│  ┌─────────────────────────────┐                   │
│  │   Sandbox (File System)     │                   │
│  │   ~/planner-sandbox/        │                   │
│  │   ├── instructions/         │                   │
│  │   ├── daily/                │                   │
│  │   ├── reflections/          │                   │
│  │   ├── notes/                │                   │
│  │   └── config/               │                   │
│  └─────────────────────────────┘                   │
└─────────────────────────────────────────────────────┘
```

## Tech Stack

- **Language:** Python 3.12+
- **Package Manager:** Poetry
- **Telegram:** `python-telegram-bot` (v20+, async)
- **AI SDK:** `anthropic` (official Python SDK)
- **Config:** `.env` file via `python-dotenv`
- **Async:** `asyncio` throughout

## Project Structure

```
planner-agent/
├── pyproject.toml
├── .env                          # secrets (gitignored)
├── .env.example
├── README.md
├── sandbox/                      # the sandboxed file environment
│   ├── instructions/
│   │   ├── system_prompt.md      # agent persona & rules
│   │   ├── day_planner.md        # day planning instructions
│   │   └── eod_reflection.md    # EOD reflection instructions
│   ├── daily/                    # daily plans (YYYY-MM-DD.md)
│   ├── reflections/              # EOD reflections (YYYY-MM-DD.md)
│   ├── notes/                    # freeform notes
│   └── config/
│       └── preferences.yaml      # user preferences
├── src/
│   └── planner_agent/
│       ├── __init__.py
│       ├── main.py               # entrypoint
│       ├── orchestrator.py       # message routing & session mgmt
│       ├── sandbox/
│       │   ├── __init__.py
│       │   └── file_manager.py   # sandboxed file read/write
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py           # abstract Agent interface
│       │   └── claude_agent.py   # Claude implementation
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py           # abstract Adapter interface
│       │   └── telegram.py       # Telegram adapter
│       └── tools/
│           ├── __init__.py
│           └── definitions.py    # tool schemas for the agent
└── tests/
    ├── __init__.py
    ├── test_sandbox.py
    ├── test_orchestrator.py
    └── test_claude_agent.py
```

## Core Interfaces

### 1. Adapter Interface (`src/planner_agent/adapters/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Awaitable


@dataclass
class IncomingMessage:
    user_id: str
    text: str
    adapter_name: str
    raw: dict | None = None  # adapter-specific payload


@dataclass
class OutgoingMessage:
    user_id: str
    text: str
    metadata: dict | None = None


class BaseAdapter(ABC):
    """Abstract base for all communication adapters."""

    @abstractmethod
    async def start(self, on_message: Callable[[IncomingMessage], Awaitable[OutgoingMessage]]) -> None:
        """Start listening for messages. Call on_message for each incoming message."""
        ...

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> None:
        """Send a message back to the user."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the adapter."""
        ...
```

### 2. Agent Interface (`src/planner_agent/agents/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AgentResponse:
    text: str
    tool_calls_made: list[str] | None = None
    token_usage: dict | None = None  # for cost tracking


class BaseAgent(ABC):
    """Abstract base for all AI agent backends."""

    @abstractmethod
    async def run(self, user_message: str, conversation_history: list[dict], system_prompt: str) -> AgentResponse:
        """
        Process a user message with full conversation history.
        The agent may call tools (file read/write) in an agentic loop.
        Returns the final response.
        """
        ...
```

### 3. Sandbox File Manager (`src/planner_agent/sandbox/file_manager.py`)

```python
import os
from pathlib import Path


class SandboxFileManager:
    """
    Provides sandboxed file read/write. All paths are resolved
    relative to the sandbox root. Path traversal is blocked.
    """

    def __init__(self, sandbox_root: str | Path):
        self.root = Path(sandbox_root).resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True)

    def _resolve_safe(self, relative_path: str) -> Path:
        target = (self.root / relative_path).resolve()
        if not str(target).startswith(str(self.root)):
            raise PermissionError(f"Path traversal blocked: {relative_path}")
        return target

    def read_file(self, relative_path: str) -> str:
        path = self._resolve_safe(relative_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        return path.read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str) -> str:
        path = self._resolve_safe(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Written to {relative_path}"

    def list_files(self, relative_dir: str = ".") -> list[str]:
        dir_path = self._resolve_safe(relative_dir)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {relative_dir}")
        return [
            str(p.relative_to(self.root))
            for p in dir_path.rglob("*")
            if p.is_file()
        ]
```

### 4. Tool Definitions (`src/planner_agent/tools/definitions.py`)

These are the tools the Claude agent can call in its agentic loop:

```python
TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the sandbox. Use this to read instructions, daily plans, reflections, notes, or config.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the sandbox (e.g. 'instructions/system_prompt.md', 'daily/2025-01-15.md')"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the sandbox. Use this to create/update daily plans, reflections, and notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the sandbox"
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "list_files",
        "description": "List all files in a sandbox directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Relative directory path (default: root)",
                    "default": "."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_current_datetime",
        "description": "Get the current date and time in the user's timezone.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]
```

### 5. Claude Agent (`src/planner_agent/agents/claude_agent.py`)

Key behavior:
- Uses Anthropic SDK with tool use
- Runs an **agentic loop**: sends message → if Claude responds with tool calls → execute tools → feed results back → repeat until Claude gives a text response
- Tracks token usage for cost control

```python
# Pseudocode for the agentic loop
async def run(self, user_message, conversation_history, system_prompt) -> AgentResponse:
    messages = [*conversation_history, {"role": "user", "content": user_message}]
    total_tokens = {"input": 0, "output": 0}

    while True:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        total_tokens["input"] += response.usage.input_tokens
        total_tokens["output"] += response.usage.output_tokens

        # If stop_reason is "end_turn", extract text and return
        if response.stop_reason == "end_turn":
            return AgentResponse(text=extract_text(response), token_usage=total_tokens)

        # If stop_reason is "tool_use", execute each tool call
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_block in get_tool_blocks(response):
                result = self.execute_tool(tool_block.name, tool_block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})
            continue  # loop again

        break  # safety exit
```

### 6. Orchestrator (`src/planner_agent/orchestrator.py`)

- Maintains per-user conversation history (in-memory for MVP, can be persisted later)
- Loads system prompt from `sandbox/instructions/system_prompt.md`
- Routes incoming messages to the agent and returns responses
- Enforces a **max turns per request** limit (e.g., 10) to cap cost

```python
class Orchestrator:
    def __init__(self, agent: BaseAgent, sandbox: SandboxFileManager, max_turns: int = 10):
        self.agent = agent
        self.sandbox = sandbox
        self.max_turns = max_turns
        self.conversations: dict[str, list[dict]] = {}  # user_id -> history

    async def handle_message(self, incoming: IncomingMessage) -> OutgoingMessage:
        system_prompt = self.sandbox.read_file("instructions/system_prompt.md")
        history = self.conversations.get(incoming.user_id, [])

        response = await self.agent.run(incoming.text, history, system_prompt)

        # Update history
        history.append({"role": "user", "content": incoming.text})
        history.append({"role": "assistant", "content": response.text})
        self.conversations[incoming.user_id] = history

        return OutgoingMessage(user_id=incoming.user_id, text=response.text)
```

### 7. Entrypoint (`src/planner_agent/main.py`)

```python
import asyncio
from planner_agent.sandbox.file_manager import SandboxFileManager
from planner_agent.agents.claude_agent import ClaudeAgent
from planner_agent.adapters.telegram import TelegramAdapter
from planner_agent.orchestrator import Orchestrator


async def main():
    sandbox = SandboxFileManager("./sandbox")
    agent = ClaudeAgent(model="claude-sonnet-4-20250514")
    orchestrator = Orchestrator(agent=agent, sandbox=sandbox)
    adapter = TelegramAdapter()

    await adapter.start(on_message=orchestrator.handle_message)


if __name__ == "__main__":
    asyncio.run(main())
```

## pyproject.toml

```toml
[tool.poetry]
name = "planner-agent"
version = "0.1.0"
description = "Self-hosted agentic day planner with sandboxed file access"
authors = ["rishabh"]
readme = "README.md"
packages = [{include = "planner_agent", from = "src"}]

[tool.poetry.dependencies]
python = "^3.12"
anthropic = "^0.49"
python-telegram-bot = "^21"
python-dotenv = "^1.1"
pyyaml = "^6.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-asyncio = "^0.25"
ruff = "^0.11"

[tool.poetry.scripts]
planner = "planner_agent.main:main"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

## .env.example

```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
ALLOWED_TELEGRAM_USER_IDS=123456789  # comma-separated, for auth
SANDBOX_PATH=./sandbox
CLAUDE_MODEL=claude-sonnet-4-20250514
MAX_AGENT_TURNS=10
```

## Sandbox Default Files

### `sandbox/instructions/system_prompt.md`

```markdown
You are a personal day planner and reflection assistant.

## Your capabilities
- Create and manage daily plans
- Conduct end-of-day reflections
- Take and organize notes
- Track habits and goals

## Rules
1. Always read the relevant instruction file before performing a task
   (e.g., read `instructions/day_planner.md` before creating a plan).
2. Store daily plans in `daily/YYYY-MM-DD.md`.
3. Store reflections in `reflections/YYYY-MM-DD.md`.
4. Store notes in `notes/` with descriptive filenames.
5. Always check what already exists before creating new files.
6. Be concise but warm in your responses.
7. Use get_current_datetime to know the current date/time.
```

### `sandbox/instructions/day_planner.md`

```markdown
## Day Planning Instructions

When the user asks to plan their day:
1. Check if a plan for today already exists in `daily/`
2. Ask about their top 3 priorities if not provided
3. Ask about any fixed appointments/meetings
4. Create a structured plan with time blocks
5. Save to `daily/YYYY-MM-DD.md`

Format:
# Daily Plan - YYYY-MM-DD

## Top Priorities
1. ...

## Schedule
- [ ] 09:00 - ...
- [ ] 10:00 - ...

## Notes
...
```

### `sandbox/instructions/eod_reflection.md`

```markdown
## EOD Reflection Instructions

When the user wants to do an end-of-day reflection:
1. Read today's plan from `daily/YYYY-MM-DD.md`
2. Ask what they accomplished
3. Ask what went well
4. Ask what could improve
5. Ask about tomorrow's intentions
6. Save to `reflections/YYYY-MM-DD.md`
```

## Cost Control Mechanisms

| Mechanism | Implementation |
|---|---|
| **Max agent turns per request** | `MAX_AGENT_TURNS` env var, enforced in agentic loop |
| **Token tracking** | Every `AgentResponse` includes `token_usage` dict |
| **Model selection** | Configurable via env var; default to Sonnet for cost efficiency |
| **User allowlist** | `ALLOWED_TELEGRAM_USER_IDS` prevents unauthorized usage |
| **Conversation history limit** | Keep last N messages (e.g., 50) per user, trim oldest |

## Security Considerations

- **Sandbox isolation:** All file paths resolved and validated against the sandbox root; path traversal blocked
- **Telegram auth:** Only messages from allowlisted user IDs are processed
- **No shell access:** The agent has no tool to execute arbitrary commands
- **Secrets in `.env`:** Never committed to git

## MVP Scope (Build This First)

1. ✅ Sandbox file manager with path safety
2. ✅ Claude agent with tool-use agentic loop
3. ✅ Telegram adapter (async, single-user)
4. ✅ Orchestrator with in-memory conversation history
5. ✅ Default instruction files for day planning and EOD reflection
6. ✅ Token usage logging to stdout
7. ✅ Basic tests for sandbox and orchestrator

## Future Enhancements (Not MVP)

- Persistent conversation history (SQLite)
- Scheduled messages (morning plan prompt, evening reflection prompt)
- CLI adapter for local testing without Telegram
- OpenAI/Ollama agent adapters
- Web dashboard for viewing plans/reflections
- Cost dashboard with daily/monthly token spend
- Multi-user support with per-user sandboxes

## Build Command Sequence

```bash
poetry new planner-agent --src
cd planner-agent
poetry add anthropic python-telegram-bot python-dotenv pyyaml
poetry add --group dev pytest pytest-asyncio ruff
# Create directory structure as specified above
# Copy .env.example to .env and fill in keys
poetry run python -m planner_agent.main
```
