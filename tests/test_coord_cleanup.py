"""Tests for harness.coord.coordinator cleanup_run + cleanup_all_completed."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.coord.coordinator import (
    CleanupReport,
    cleanup_all_completed,
    cleanup_run,
)


def _setup_fake_run(
    repo: Path,
    run_id: str,
    state: str = "completed",
    with_worktrees: bool = True,
    with_deliverables: bool = True,
) -> None:
    """Materialise a fake run directory + worktree under *repo*."""
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_state.json").write_text(
        json.dumps({
            "schema_version": 1,
            "run_id": run_id,
            "spec_path": "spec/dummy.md",
            "state": state,
            "plan_path": str(run_dir / "plan.json"),
            "started_at": "2026-05-21T00:00:00Z",
            "last_tick_at": "2026-05-21T00:05:00Z",
            "workers": {},
        }),
        encoding="utf-8",
    )
    (run_dir / "plan.json").write_text('{"dummy": true}', encoding="utf-8")
    if with_deliverables:
        deliv = run_dir / "deliverables"
        deliv.mkdir(exist_ok=True)
        (deliv / "worker-1.json").write_text('{"state": "completed"}', encoding="utf-8")
    ckpt_dir = run_dir / "checkpoints"
    ckpt_dir.mkdir(exist_ok=True)
    (ckpt_dir / "worker-1.json").write_text('{"state": "completed"}', encoding="utf-8")

    if with_worktrees:
        wt_dir = repo / ".harness" / "worktrees" / run_id / "worker-1"
        wt_dir.mkdir(parents=True, exist_ok=True)
        (wt_dir / "dummy.txt").write_text("x" * 1024, encoding="utf-8")


class TestCleanupRun:
    def test_completed_run_removed(self, tmp_path: Path) -> None:
        _setup_fake_run(tmp_path, "20260521T000000-aaaa", state="completed")
        with patch("harness.coord.coordinator.subprocess.run"):
            report = cleanup_run(
                "20260521T000000-aaaa",
                repo_root=tmp_path,
            )
        assert isinstance(report, CleanupReport)
        assert "20260521T000000-aaaa" in report.runs_removed
        assert len(report.worktrees_removed) >= 1
        assert report.bytes_freed > 0
        # Worktree dir gone
        assert not (tmp_path / ".harness" / "worktrees" / "20260521T000000-aaaa").exists()

    def test_running_run_skipped(self, tmp_path: Path) -> None:
        _setup_fake_run(tmp_path, "20260521T000000-bbbb", state="running")
        report = cleanup_run(
            "20260521T000000-bbbb",
            repo_root=tmp_path,
        )
        assert report.runs_removed == []
        assert "20260521T000000-bbbb" in report.skipped_active
        # Worktree preserved
        assert (tmp_path / ".harness" / "worktrees" / "20260521T000000-bbbb").exists()

    def test_dry_run_does_not_delete(self, tmp_path: Path) -> None:
        _setup_fake_run(tmp_path, "20260521T000000-cccc", state="completed")
        report = cleanup_run(
            "20260521T000000-cccc",
            repo_root=tmp_path,
            dry_run=True,
        )
        assert report.dry_run is True
        assert report.bytes_freed > 0
        # Worktree still present
        assert (tmp_path / ".harness" / "worktrees" / "20260521T000000-cccc").exists()
        assert (tmp_path / "runs" / "20260521T000000-cccc").exists()

    def test_keep_deliverables(self, tmp_path: Path) -> None:
        _setup_fake_run(tmp_path, "20260521T000000-dddd", state="completed")
        with patch("harness.coord.coordinator.subprocess.run"):
            report = cleanup_run(
                "20260521T000000-dddd",
                repo_root=tmp_path,
                keep_deliverables=True,
            )
        # Worktrees removed
        assert not (tmp_path / ".harness" / "worktrees" / "20260521T000000-dddd").exists()
        # Deliverables + plan preserved
        run_dir = tmp_path / "runs" / "20260521T000000-dddd"
        assert (run_dir / "deliverables" / "worker-1.json").exists()
        assert (run_dir / "plan.json").exists()


class TestCleanupAllCompleted:
    def test_iterates_only_completed(self, tmp_path: Path) -> None:
        _setup_fake_run(tmp_path, "20260521T000000-eeee", state="completed")
        _setup_fake_run(tmp_path, "20260521T000000-ffff", state="failed")
        _setup_fake_run(tmp_path, "20260521T000000-aaab", state="running")
        with patch("harness.coord.coordinator.subprocess.run"):
            report = cleanup_all_completed(repo_root=tmp_path)
        # Two non-active runs removed
        assert len(report.runs_removed) == 2
        # One active skipped
        assert "20260521T000000-aaab" in report.skipped_active

    def test_no_runs_dir(self, tmp_path: Path) -> None:
        # No runs/ created — should return empty report cleanly.
        report = cleanup_all_completed(repo_root=tmp_path)
        assert report.runs_removed == []
        assert report.bytes_freed == 0


class TestCleanupCLI:
    def test_help(self) -> None:
        from harness.cli import cli
        result = CliRunner().invoke(cli, ["coord", "cleanup", "--help"])
        assert result.exit_code == 0
        for opt in ("--run-id", "--dry-run", "--keep-deliverables", "--force"):
            assert opt in result.output

    def test_dry_run_force(self, tmp_path: Path) -> None:
        from harness.cli import cli
        # No runs anywhere — should still exit 0 cleanly.
        with patch("harness.coord.coordinator.Path.cwd", return_value=tmp_path):
            result = CliRunner().invoke(
                cli, ["coord", "cleanup", "--dry-run", "--force"]
            )
        assert result.exit_code == 0
        assert "runs cleared: 0" in result.output.lower() or "dry-run" in result.output.lower()
