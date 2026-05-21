"""Tests for WORKER-TOKEN-COST-TAG: worker accumulates token + cost telemetry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.coord.schemas import WorkerStep, WorkerTask


def _mk_task(target_files: list[str]) -> dict:
    return WorkerTask(
        worker_id="worker-1",
        title="t",
        description="d",
        steps=[WorkerStep(
            step_id="s1", kind="edit", instruction="x",
            target_files=target_files, expected_diff_lines=1,
        )],
    ).model_dump()


def test_run_worker_accumulates_tokens_from_dispatch(tmp_path: Path, monkeypatch) -> None:
    """worker.run_worker pulls tokens_used / cost_usd off EngineResponse."""
    from harness.coord import worker as worker_module

    # Stub dispatch_packet to return a fake DispatchResult with telemetry
    fake_result = MagicMock(
        success=True,
        text="FILE: x.txt\n<<<<<<< SEARCH\n=======\nhello\n>>>>>>> REPLACE\n",
        tokens_used=123,
        cost_usd=0.45,
    )
    monkeypatch.setattr(
        "harness.engines.dispatcher.dispatch_packet", lambda **kw: fake_result,
    )

    # Stub git operations (worker tries to commit)
    monkeypatch.setattr(worker_module, "_git_commit", lambda *a, **kw: "deadbee")

    # Stub pytest
    monkeypatch.setattr(worker_module, "_run_pytest", lambda *a, **kw: {
        "ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0,
    })

    # Stub worktree to use a real tmp dir
    monkeypatch.setattr(worker_module, "worktree_path", lambda *a, **kw: tmp_path / "wt")
    (tmp_path / "wt").mkdir()

    run_dir = tmp_path / "runs" / "test-run"
    run_dir.mkdir(parents=True)

    result = worker_module.run_worker(
        _mk_task(["x.txt"]), run_dir, engine="mock", project_root=tmp_path,
    )

    assert result["tokens_used"] == 123
    assert result["cost_usd"] == pytest.approx(0.45)


def test_run_worker_handles_missing_telemetry_gracefully(tmp_path: Path, monkeypatch) -> None:
    """Old-shape EngineResponse (no tokens_used / cost_usd) doesn't crash."""
    from harness.coord import worker as worker_module

    fake_result = MagicMock(
        success=True,
        text="FILE: x.txt\n<<<<<<< SEARCH\n=======\nhi\n>>>>>>> REPLACE\n",
        spec=["success", "text"],  # no tokens_used / cost_usd attrs
    )
    monkeypatch.setattr(
        "harness.engines.dispatcher.dispatch_packet", lambda **kw: fake_result,
    )
    monkeypatch.setattr(worker_module, "_git_commit", lambda *a, **kw: "deadbee")
    monkeypatch.setattr(worker_module, "_run_pytest", lambda *a, **kw: {
        "ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0,
    })
    monkeypatch.setattr(worker_module, "worktree_path", lambda *a, **kw: tmp_path / "wt")
    (tmp_path / "wt").mkdir()

    run_dir = tmp_path / "runs" / "test-run-2"
    run_dir.mkdir(parents=True)

    result = worker_module.run_worker(
        _mk_task(["x.txt"]), run_dir, engine="mock", project_root=tmp_path,
    )
    assert result["tokens_used"] == 0
    assert result["cost_usd"] == 0.0
