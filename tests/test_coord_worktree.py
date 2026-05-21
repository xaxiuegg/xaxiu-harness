"""Tests for harness.coord.worktree."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.coord.worktree import (
    create_worktree,
    list_worktrees,
    remove_worktree,
    worker_branch_name,
    worktree_path,
)


# ---------------------------------------------------------------------------
# worker_branch_name
# ---------------------------------------------------------------------------

def test_worker_branch_name_pattern() -> None:
    assert worker_branch_name("20260520T220000-ab12", "worker-1") == "wt/20260520T220000-ab12/worker-1"


# ---------------------------------------------------------------------------
# worktree_path
# ---------------------------------------------------------------------------

def test_worktree_path_default_root() -> None:
    p = worktree_path("run-1", "worker-1")
    assert p == Path(".harness") / "worktrees" / "run-1" / "worker-1"


def test_worktree_path_custom_root() -> None:
    root = Path("/tmp/harness")
    p = worktree_path("run-1", "worker-1", root=root)
    assert p == Path("/tmp/harness") / "run-1" / "worker-1"


# ---------------------------------------------------------------------------
# create_worktree
# ---------------------------------------------------------------------------

def test_create_worktree_creates_path_and_branch(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    worker_id = "worker-1"
    expected_path = tmp_path / ".harness" / "worktrees" / run_id / worker_id

    with patch("harness.coord.worktree.subprocess.run") as mock_run:
        result = create_worktree(run_id, worker_id, repo_root=tmp_path)

    assert result == expected_path
    mock_run.assert_called_once_with(
        [
            "git", "worktree", "add", str(expected_path),
            "-b", f"wt/{run_id}/{worker_id}", "master",
        ],
        check=True, cwd=tmp_path, capture_output=True,
    )


def test_create_worktree_idempotent(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    worker_id = "worker-1"
    expected_path = tmp_path / ".harness" / "worktrees" / run_id / worker_id
    expected_path.mkdir(parents=True)

    with patch("harness.coord.worktree.subprocess.run") as mock_run:
        result = create_worktree(run_id, worker_id, repo_root=tmp_path)

    assert result == expected_path
    mock_run.assert_not_called()


def test_create_worktree_custom_base_branch(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    worker_id = "worker-1"
    expected_path = tmp_path / ".harness" / "worktrees" / run_id / worker_id

    with patch("harness.coord.worktree.subprocess.run") as mock_run:
        create_worktree(run_id, worker_id, base_branch="develop", repo_root=tmp_path)

    mock_run.assert_called_once_with(
        [
            "git", "worktree", "add", str(expected_path),
            "-b", f"wt/{run_id}/{worker_id}", "develop",
        ],
        check=True, cwd=tmp_path, capture_output=True,
    )


# ---------------------------------------------------------------------------
# remove_worktree
# ---------------------------------------------------------------------------

def test_remove_worktree_missing_returns_false(tmp_path: Path) -> None:
    assert remove_worktree("run-1", "worker-1", repo_root=tmp_path) is False


def test_remove_worktree_deletes_and_returns_true(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    worker_id = "worker-1"
    path = tmp_path / ".harness" / "worktrees" / run_id / worker_id
    path.mkdir(parents=True)

    with patch("harness.coord.worktree.subprocess.run") as mock_run:
        # Simulate removal by having path not exist after subprocess
        mock_run.return_value = MagicMock(returncode=0)
        with patch.object(Path, "exists", side_effect=[True, False]):
            result = remove_worktree(run_id, worker_id, repo_root=tmp_path)

    assert result is True
    mock_run.assert_called_once_with(
        ["git", "worktree", "remove", str(path)],
        check=False, cwd=tmp_path, capture_output=True,
    )


def test_remove_worktree_force_appends_flag(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    worker_id = "worker-1"
    path = tmp_path / ".harness" / "worktrees" / run_id / worker_id
    path.mkdir(parents=True)

    with patch("harness.coord.worktree.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch.object(Path, "exists", side_effect=[True, False]):
            remove_worktree(run_id, worker_id, repo_root=tmp_path, force=True)

    mock_run.assert_called_once_with(
        ["git", "worktree", "remove", str(path), "--force"],
        check=False, cwd=tmp_path, capture_output=True,
    )


# ---------------------------------------------------------------------------
# list_worktrees
# ---------------------------------------------------------------------------

def test_list_worktrees_parses_porcelain_output(tmp_path: Path) -> None:
    porcelain = (
        "worktree /home/repo\n"
        "bare\n"
        "worktree /home/repo/.harness/worktrees/run-1/worker-1\n"
        "branch refs/heads/wt/run-1/worker-1\n"
        "worktree /home/repo/.harness/worktrees/run-1/worker-2\n"
        "branch refs/heads/wt/run-1/worker-2\n"
        "worktree /other/path\n"
        "detached\n"
    )

    with patch(
        "harness.coord.worktree.subprocess.run",
        return_value=MagicMock(stdout=porcelain, returncode=0),
    ) as mock_run:
        result = list_worktrees(repo_root=tmp_path)

    mock_run.assert_called_once_with(
        ["git", "worktree", "list", "--porcelain"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert len(result) == 2
    assert str(result[0]).replace("\\", "/") == "/home/repo/.harness/worktrees/run-1/worker-1"
    assert str(result[1]).replace("\\", "/") == "/home/repo/.harness/worktrees/run-1/worker-2"


def test_list_worktrees_empty_on_no_matches(tmp_path: Path) -> None:
    porcelain = (
        "worktree /home/repo\n"
        "bare\n"
    )

    with patch(
        "harness.coord.worktree.subprocess.run",
        return_value=MagicMock(stdout=porcelain, returncode=0),
    ):
        result = list_worktrees(repo_root=tmp_path)

    assert result == []
