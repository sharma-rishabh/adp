"""Filesystem-backed sandbox implementation.

All paths are resolved relative to a designated root directory.
Any attempt to escape the root via ``../`` or symlinks is rejected.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..exceptions import (
    SandboxFileNotFoundError,
    SandboxNotADirectoryError,
    SandboxPathTraversalError,
)
from ..sandbox.base import BaseSandbox

logger = logging.getLogger(__name__)


class SandboxFileManager(BaseSandbox):
    """Sandboxed file manager backed by the local filesystem.

    Args:
        sandbox_root: Absolute or relative path to the sandbox directory.
            Created automatically if it does not exist.
    """

    def __init__(self, sandbox_root: str | Path) -> None:
        self.root = Path(sandbox_root).resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True)
            logger.info("Created sandbox root at %s", self.root)

    def _resolve_safe(self, relative_path: str) -> Path:
        """Resolve *relative_path* inside the sandbox, blocking traversal.

        Args:
            relative_path: A path relative to the sandbox root.

        Returns:
            The resolved absolute ``Path``.

        Raises:
            SandboxPathTraversalError: If the resolved path falls
                outside the sandbox root.
        """
        target = (self.root / relative_path).resolve()
        if not target.is_relative_to(self.root):
            logger.warning("Path traversal blocked: %s -> %s", relative_path, target)
            raise SandboxPathTraversalError(f"Path traversal blocked: {relative_path}")
        return target

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
        path = self._resolve_safe(relative_path)
        if not path.exists():
            raise SandboxFileNotFoundError(f"File not found: {relative_path}")
        logger.debug("Reading %s", relative_path)
        return path.read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str) -> str:
        """Write (or overwrite) a file in the sandbox.

        Args:
            relative_path: Path relative to sandbox root.
            content: Full file content to write.

        Returns:
            A confirmation message.

        Raises:
            SandboxPathTraversalError: If the path escapes the sandbox.
        """
        path = self._resolve_safe(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.debug("Wrote %s (%d bytes)", relative_path, len(content))
        return f"Written to {relative_path}"

    def list_files(self, relative_dir: str = ".") -> list[str]:
        """Recursively list all files under a sandbox directory.

        Args:
            relative_dir: Directory path relative to sandbox root.

        Returns:
            A sorted list of relative file paths.

        Raises:
            SandboxNotADirectoryError: If the path is not a directory.
            SandboxPathTraversalError: If the path escapes the sandbox.
        """
        dir_path = self._resolve_safe(relative_dir)
        if not dir_path.is_dir():
            raise SandboxNotADirectoryError(f"Not a directory: {relative_dir}")
        files = sorted(
            str(p.relative_to(self.root))
            for p in dir_path.rglob("*")
            if p.is_file()
        )
        logger.debug("Listed %d files in %s", len(files), relative_dir)
        return files

    @property
    def palace_path(self) -> Path:
        """Path to the MemPalace store inside the sandbox."""
        path = self.root / "palace"
        path.mkdir(exist_ok=True)
        return path

