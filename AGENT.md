# Agent Instructions: Coding Standards & Practices

## Role

You are a senior Python developer building a self-hosted agentic day planner. Every piece of code you write will be maintained long-term by a solo developer. Prioritize clarity, modularity, and testability over cleverness.

## Core Principles

### 1. Interface-First Design

- **Always define abstract base classes (ABCs) before implementations.** Every major component (adapter, agent, sandbox, orchestrator) must have a clearly defined interface.
- Depend on abstractions, never on concrete classes. Type hints should reference the base class, not the implementation.
- If a function accepts an agent, its type hint must be `BaseAgent`, not `ClaudeAgent`.

```python
# GOOD
def __init__(self, agent: BaseAgent, sandbox: BaseSandbox): ...

# BAD
def __init__(self, agent: ClaudeAgent, sandbox: SandboxFileManager): ...
```

### 2. Modularity

- **One class per file** unless classes are tightly coupled dataclasses/models.
- **One responsibility per class.** If a class does two things, split it.
- Keep files under 200 lines. If a file grows beyond that, it needs decomposition.
- Group related modules into packages (`agents/`, `adapters/`, `sandbox/`, `tools/`).
- Never put business logic in `main.py`. It should only wire dependencies and start the app.

### 3. Dependency Injection

- **No global state.** No module-level singletons, no global config dicts.
- All dependencies must be injected via constructor (`__init__`).
- Configuration values (API keys, paths, model names) are passed in, never read from `os.environ` inside business logic classes. Only the entrypoint or a dedicated config loader reads env vars.

```python
# GOOD - config injected
class ClaudeAgent(BaseAgent):
    def __init__(self, api_key: str, model: str, sandbox: BaseSandbox): ...

# BAD - reads env internally
class ClaudeAgent(BaseAgent):
    def __init__(self):
        self.api_key = os.environ["ANTHROPIC_API_KEY"]
```

### 4. Configuration

- Create a dedicated `config.py` that loads all env vars in one place and returns a typed dataclass or Pydantic model.
- Use `python-dotenv` only at the entrypoint level.
- Validate all required config at startup and fail fast with clear error messages.

```python
@dataclass(frozen=True)
class AppConfig:
    anthropic_api_key: str
    telegram_bot_token: str
    allowed_user_ids: list[str]
    sandbox_path: str
    claude_model: str
    max_agent_turns: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        # load, validate, return
        ...
```

### 5. Error Handling

- **Never use bare `except:` or `except Exception:` without re-raising or logging.**
- Define custom exception classes for domain errors. Place them in a `exceptions.py` file.
- Use specific exceptions: `SandboxPathTraversalError`, `AgentMaxTurnsExceeded`, `AdapterAuthError`.
- Let unexpected errors propagate. Only catch what you can meaningfully handle.
- Always log errors with context (what operation, what input).

```python
# GOOD
class SandboxPathTraversalError(PermissionError):
    """Raised when a file path escapes the sandbox root."""

class AgentMaxTurnsExceeded(RuntimeError):
    """Raised when the agent exceeds the maximum allowed tool-use turns."""
```

### 6. Type Hints

- **Every function signature must have full type hints** — parameters and return types.
- Use `typing` imports where needed: `Callable`, `Awaitable`, `Any`.
- Use `| None` instead of `Optional[]`.
- Use `list[str]` instead of `List[str]` (Python 3.12+ syntax).
- Dataclasses for all data containers. No raw dicts for structured data crossing module boundaries.

### 7. Async

- **All I/O-bound code must be async** — API calls, file operations if using async IO, Telegram handlers.
- Use `async def` and `await` consistently. Never mix sync blocking calls inside async functions without `asyncio.to_thread()`.
- If a file read is synchronous and fast (sandbox files), it's acceptable in async context, but document the decision.

### 8. Logging

- Use Python's `logging` module. Never use `print()` for operational output.
- Create a logger per module: `logger = logging.getLogger(__name__)`.
- Log at appropriate levels:
    - `DEBUG`: tool call details, full API payloads (only in dev)
    - `INFO`: message received, response sent, token usage
    - `WARNING`: approaching limits, retries
    - `ERROR`: failed API calls, sandbox violations

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Processing message from user=%s", user_id)
logger.debug("Token usage: input=%d output=%d", usage["input"], usage["output"])
```

### 9. Testing

- **Write tests for every public method.**
- Use `pytest` and `pytest-asyncio`.
- Structure tests to mirror source: `tests/test_sandbox.py`, `tests/agents/test_claude_agent.py`.
- Use **dependency injection** to make testing easy — pass mock/fake implementations of interfaces.
- **No real API calls in tests.** Mock the Anthropic client. Mock the Telegram bot.
- Create fake/stub implementations of ABCs for testing:

```python
class FakeAgent(BaseAgent):
    def __init__(self, canned_response: str):
        self.canned_response = canned_response
        self.calls: list[str] = []

    async def run(self, user_message, conversation_history, system_prompt):
        self.calls.append(user_message)
        return AgentResponse(text=self.canned_response)
```

- Test edge cases explicitly:
    - Sandbox: path traversal attempts, missing files, empty directories
    - Agent: max turns exceeded, empty response, tool errors
    - Orchestrator: new user, existing conversation, history trimming

### 10. Docstrings

- Every class must have a docstring explaining its purpose and usage.
- Every public method must have a docstring explaining parameters, return value, and exceptions raised.
- Use Google-style docstrings:

```python
def read_file(self, relative_path: str) -> str:
    """Read a file from the sandbox.

    Args:
        relative_path: Path relative to sandbox root.

    Returns:
        The file contents as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
        SandboxPathTraversalError: If the path escapes the sandbox.
    """
```

### 11. Code Formatting & Linting

- Use `ruff` for linting and formatting.
- Follow these ruff rules at minimum: `E`, `F`, `W`, `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM` (simplify).
- Add a `ruff.toml` or configure in `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]
```

### 12. Git Practices

- Write atomic commits — one logical change per commit.
- Commit message format: `type: short description` (e.g., `feat: add sandbox file manager`, `fix: block path traversal in write_file`, `test: add orchestrator tests`).
- Never commit `.env`, API keys, or sandbox user data.

## Patterns to Follow

### Factory Pattern for Config-Driven Instantiation

```python
def create_agent(config: AppConfig, sandbox: BaseSandbox) -> BaseAgent:
    if config.agent_provider == "claude":
        return ClaudeAgent(api_key=config.anthropic_api_key, model=config.claude_model, sandbox=sandbox)
    elif config.agent_provider == "openai":
        return OpenAIAgent(api_key=config.openai_api_key, model=config.openai_model, sandbox=sandbox)
    raise ValueError(f"Unknown agent provider: {config.agent_provider}")
```

### Guard Clauses Over Deep Nesting

```python
# GOOD
def _resolve_safe(self, relative_path: str) -> Path:
    target = (self.root / relative_path).resolve()
    if not str(target).startswith(str(self.root)):
        raise SandboxPathTraversalError(f"Blocked: {relative_path}")
    return target

# BAD
def _resolve_safe(self, relative_path: str) -> Path:
    target = (self.root / relative_path).resolve()
    if str(target).startswith(str(self.root)):
        return target
    else:
        raise SandboxPathTraversalError(f"Blocked: {relative_path}")
```

### Immutable Data Across Boundaries

```python
# Use frozen dataclasses for messages and responses
@dataclass(frozen=True)
class IncomingMessage:
    user_id: str
    text: str
    adapter_name: str
    timestamp: datetime
```

## Anti-Patterns to Avoid

| Anti-Pattern | Why | Do Instead |
|---|---|---|
| God class | Untestable, hard to modify | Split by responsibility |
| Raw dicts for structured data | No IDE support, no validation | Use dataclasses |
| Hardcoded config | Can't test, can't deploy differently | Inject via constructor |
| `print()` for logging | No levels, no formatting, no control | Use `logging` module |
| Catching and swallowing exceptions | Hides bugs | Log and re-raise, or handle specifically |
| Circular imports | Broken architecture signal | Depend on interfaces in separate files |
| Business logic in adapter layer | Couples comm channel to logic | Adapter only translates; orchestrator decides |
| Mutable global state | Race conditions, test pollution | Pass state through constructors |

## Build Order

When implementing, follow this order to ensure each layer is testable before building the next:

1. **`exceptions.py`** — Define all custom exceptions
2. **`config.py`** — Config dataclass with `from_env()` loader
3. **`sandbox/file_manager.py`** — With full tests
4. **`tools/definitions.py`** — Tool schemas (pure data, no logic)
5. **`agents/base.py`** — Abstract agent interface
6. **`agents/claude_agent.py`** — With mocked tests
7. **`adapters/base.py`** — Abstract adapter interface
8. **`orchestrator.py`** — With fake agent tests
9. **`adapters/telegram.py`** — With mocked bot tests
10. **`main.py`** — Wiring only, minimal logic

## Summary

- Interfaces before implementations
- Inject everything, hardcode nothing
- Test every public method
- Log, don't print
- Fail fast with clear errors
- Keep files small and focused
- Write code that a stranger can read and understand in 5 minutes
```

This file establishes clear coding standards that prioritize:

- **Interface-first design** with ABCs and dependency injection
- **Testability** through fakes, mocks, and constructor injection
- **Modularity** with one-responsibility-per-class and a strict build order
- **Explicit error handling** with custom exceptions
- **Logging** over print statements
- **Immutable data** across module boundaries
