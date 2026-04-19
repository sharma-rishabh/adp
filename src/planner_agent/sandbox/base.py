"""Abstract interface for sandboxed file operations.

Concrete implementations must confine all reads and writes to a
designated root directory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseSandbox(ABC):
    """Interface for sandboxed file I/O.

    Every method receives paths **relative** to the sandbox root and
    must reject any attempt to escape it.
    """

    @abstractmethod
    def read_file(self, relative_path: str) -> str:
        """Read a file from the sandbox.

        Args:
            relative_path: Path relative to sandbox root.

        Returns:
            The file contents as a UTF-8 string.

        Raises:
            SandboxFileNotFoundError: If the file does not exist.
            SandboxPathTraversalError: If the path escapes the sandbox.
        """

    @abstractmethod
    def write_file(self, relative_path: str, content: str) -> str:
        """Write (or overwrite) a file in the sandbox.

        Parent directories are created automatically.

        Args:
            relative_path: Path relative to sandbox root.
            content: Full file content to write.

        Returns:
            A human-readable confirmation message.

        Raises:
            SandboxPathTraversalError: If the path escapes the sandbox.
        """

    @abstractmethod
    def list_files(self, relative_dir: str = ".") -> list[str]:
        """Recursively list all files under a sandbox directory.

        Args:
            relative_dir: Directory path relative to sandbox root.

        Returns:
            A list of relative file paths (POSIX-style separators).

        Raises:
            SandboxNotADirectoryError: If the path is not a directory.
            SandboxPathTraversalError: If the path escapes the sandbox.
        """

    @property
    @abstractmethod
    def palace_path(self) -> Path:
        """Path to the MemPalace store inside the sandbox."""
