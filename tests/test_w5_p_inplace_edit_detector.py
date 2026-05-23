"""W5-P: universal in-place edit detector for agentic engines.

Kimi-CLI (xaxiu-swarm --backend kimi) is agentic — it doesn't emit
FILE/REPLACE blocks in its response, it opens files via Edit/Write
tools and edits them on disk directly.  The worker's
_parse_file_edits() returns 0 edits for such responses, but the
worktree actually has changed files.

_detect_inplace_edits() shells out to `git status --porcelain` in
the worktree to find changed files, returning relative paths.  This
is the universal fallback the worker uses when FILE/REPLACE
parsing produces 0 edits.

These tests pin contract behaviour without spinning up real engines.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.coord.worker import _detect_inplace_edits


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"],
                   check=True, capture_output=True)


def _git_commit_all(path: Path, msg: str = "initial") -> None:
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", msg],
                   check=True, capture_output=True)


def test_detects_modified_file(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("original\n", encoding="utf-8")
    _git_commit_all(tmp_path)
    # Agentic engine modifies file in-place
    (tmp_path / "a.txt").write_text("modified\n", encoding="utf-8")

    modified = _detect_inplace_edits(tmp_path)
    assert "a.txt" in modified


def test_detects_new_file(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git_commit_all(tmp_path)
    # Agentic engine adds a new file
    (tmp_path / "new.txt").write_text("hello\n", encoding="utf-8")

    modified = _detect_inplace_edits(tmp_path)
    assert "new.txt" in modified


def test_detects_multiple_changes(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    _git_commit_all(tmp_path)
    (tmp_path / "a.txt").write_text("a-modified\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("c-new\n", encoding="utf-8")

    modified = _detect_inplace_edits(tmp_path)
    assert "a.txt" in modified
    assert "c.txt" in modified


def test_empty_when_no_changes(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git_commit_all(tmp_path)
    # No agentic engine edits
    modified = _detect_inplace_edits(tmp_path)
    assert modified == []


def test_empty_when_not_a_repo(tmp_path: Path) -> None:
    """Not-a-git-repo → empty list, no crash."""
    (tmp_path / "foo.txt").write_text("hello", encoding="utf-8")
    modified = _detect_inplace_edits(tmp_path)
    assert modified == []


def test_handles_subdir_changes(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("# original\n", encoding="utf-8")
    _git_commit_all(tmp_path)
    (tmp_path / "src" / "module.py").write_text("# modified\n", encoding="utf-8")

    modified = _detect_inplace_edits(tmp_path)
    # git status emits relative paths with forward slashes
    assert any("module.py" in p for p in modified)


def test_does_not_crash_when_git_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If git binary is somehow unavailable, return [] instead of crashing."""
    def _fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")
    monkeypatch.setattr(subprocess, "run", _fake_run)
    modified = _detect_inplace_edits(tmp_path)
    assert modified == []
