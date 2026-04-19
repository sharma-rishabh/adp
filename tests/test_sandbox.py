"""Tests for the sandbox file manager.

Covers: read, write, list, path traversal blocking, missing files,
non-directory errors, and auto-creation of parent directories.
"""

from __future__ import annotations

import pytest

from planner_agent.exceptions import (
    SandboxFileNotFoundError,
    SandboxNotADirectoryError,
    SandboxPathTraversalError,
)
from planner_agent.sandbox.file_manager import SandboxFileManager


@pytest.fixture()
def sandbox(tmp_path):
    """Create a SandboxFileManager rooted in a temporary directory."""
    return SandboxFileManager(sandbox_root=tmp_path)


class TestReadFile:
    """Tests for SandboxFileManager.read_file."""

    def test_read_existing_file(self, sandbox, tmp_path):
        (tmp_path / "hello.txt").write_text("world", encoding="utf-8")
        assert sandbox.read_file("hello.txt") == "world"

    def test_read_nested_file(self, sandbox, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "deep.md").write_text("content", encoding="utf-8")
        assert sandbox.read_file("a/b/deep.md") == "content"

    def test_read_missing_file_raises(self, sandbox):
        with pytest.raises(SandboxFileNotFoundError):
            sandbox.read_file("nope.txt")

    def test_read_path_traversal_raises(self, sandbox):
        with pytest.raises(SandboxPathTraversalError):
            sandbox.read_file("../../etc/passwd")

    def test_read_path_traversal_with_hidden_escape(self, sandbox, tmp_path):
        """Ensure a path like 'subdir/../../escape' is blocked."""
        (tmp_path / "subdir").mkdir()
        with pytest.raises(SandboxPathTraversalError):
            sandbox.read_file("subdir/../../escape")


class TestWriteFile:
    """Tests for SandboxFileManager.write_file."""

    def test_write_creates_file(self, sandbox, tmp_path):
        result = sandbox.write_file("new.txt", "hello")
        assert "new.txt" in result
        assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"

    def test_write_creates_parent_dirs(self, sandbox, tmp_path):
        sandbox.write_file("a/b/c.txt", "nested")
        assert (tmp_path / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "nested"

    def test_write_overwrites_existing(self, sandbox, tmp_path):
        (tmp_path / "f.txt").write_text("old", encoding="utf-8")
        sandbox.write_file("f.txt", "new")
        assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "new"

    def test_write_path_traversal_raises(self, sandbox):
        with pytest.raises(SandboxPathTraversalError):
            sandbox.write_file("../escape.txt", "bad")


class TestListFiles:
    """Tests for SandboxFileManager.list_files."""

    def test_list_empty_dir(self, sandbox):
        assert sandbox.list_files(".") == []

    def test_list_files_in_root(self, sandbox, tmp_path):
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        result = sandbox.list_files(".")
        assert "a.txt" in result
        assert "b.txt" in result

    def test_list_files_in_subdirectory(self, sandbox, tmp_path):
        sub = tmp_path / "notes"
        sub.mkdir()
        (sub / "n1.md").write_text("x", encoding="utf-8")
        (sub / "n2.md").write_text("y", encoding="utf-8")
        result = sandbox.list_files("notes")
        assert sorted(result) == ["notes/n1.md", "notes/n2.md"]

    def test_list_files_recursive(self, sandbox, tmp_path):
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "f.txt").write_text("z", encoding="utf-8")
        result = sandbox.list_files(".")
        assert "a/b/f.txt" in result

    def test_list_non_directory_raises(self, sandbox, tmp_path):
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        with pytest.raises(SandboxNotADirectoryError):
            sandbox.list_files("file.txt")

    def test_list_path_traversal_raises(self, sandbox):
        with pytest.raises(SandboxPathTraversalError):
            sandbox.list_files("../../")

    def test_list_returns_sorted(self, sandbox, tmp_path):
        (tmp_path / "c.txt").write_text("", encoding="utf-8")
        (tmp_path / "a.txt").write_text("", encoding="utf-8")
        (tmp_path / "b.txt").write_text("", encoding="utf-8")
        result = sandbox.list_files(".")
        assert result == ["a.txt", "b.txt", "c.txt"]


class TestSandboxInit:
    """Tests for sandbox root directory creation."""

    def test_creates_root_if_missing(self, tmp_path):
        new_root = tmp_path / "brand_new"
        assert not new_root.exists()
        SandboxFileManager(sandbox_root=new_root)
        assert new_root.exists()
        assert new_root.is_dir()

