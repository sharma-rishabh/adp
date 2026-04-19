"""Custom exceptions for the planner agent.

All domain-specific errors are defined here to keep error handling
explicit and avoid bare exception catches throughout the codebase.
"""


class SandboxPathTraversalError(PermissionError):
    """Raised when a file path attempts to escape the sandbox root."""


class SandboxFileNotFoundError(FileNotFoundError):
    """Raised when a requested file does not exist in the sandbox."""


class SandboxNotADirectoryError(NotADirectoryError):
    """Raised when a path expected to be a directory is not one."""


class AgentMaxTurnsExceededError(RuntimeError):
    """Raised when the agent exceeds the maximum allowed tool-use turns."""


class AgentToolExecutionError(RuntimeError):
    """Raised when a tool call fails during the agent's agentic loop."""


class AdapterAuthError(PermissionError):
    """Raised when a message arrives from an unauthorized user."""


class ConfigValidationError(ValueError):
    """Raised when required configuration values are missing or invalid."""

