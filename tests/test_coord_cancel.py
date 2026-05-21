"""Tests for COORD-CANCEL."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.canceller import cancel_run, _terminate_pid


def _seed_run(base: Path, run_id: str, workers: dict[str, dict]) -> Path:
    from harness.coord.run_state import write_run_state
    from harness.coord.schemas import (
        IntegratorStatus, RunState, RunStateLiteral, WorkerStatus, WorkerStateLiteral,
    )
    from harness.coord.checkpoint import Checkpoint, write_checkpoint

    run_dir = base / "runs" / run_id
    (run_dir / "checkpoints").mkdir(parents=True)

    rs_workers = {}
    for wid, info in workers.items():
        rs_workers[wid] = WorkerStatus(
            worker_id=wid,
            state=WorkerStateLiteral(info.get("state", "in_progress")),
            pid=info.get("pid"),
        )
        write_checkpoint(
            run_dir / "checkpoints" / f"{wid}.json",
            Checkpoint(worker_id=wid, run_id=run_id, state=info.get("state", "in_progress")),
        )
    write_run_state(run_dir / "run_state.json", RunState(
        schema_version=1, run_id=run_id, spec_path="s.md",
        state=RunStateLiteral.RUNNING, plan_path=str(run_dir / "plan.json"),
        started_at="2026-05-21T00:00:00Z", last_tick_at="2026-05-21T00:01:00Z",
        workers=rs_workers,
        integrator_status=IntegratorStatus(state="pending"),
        escalations=[],
    ))
    return run_dir


def test_terminate_pid_zero_is_noop() -> None:
    assert _terminate_pid(0) is True


def test_cancel_run_missing_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "nope"
    run_dir.mkdir(parents=True)
    result = cancel_run(run_dir)
    assert result["success"] is False
    assert "no run_state" in result["error"]


def test_cancel_run_marks_state_and_checkpoints(tmp_path: Path) -> None:
    run_dir = _seed_run(tmp_path, "20260521T010101-aabb", {
        "worker-1": {"state": "in_progress", "pid": 99999},
        "worker-2": {"state": "completed", "pid": None},
    })
    with patch("harness.coord.canceller._terminate_pid", return_value=True):
        result = cancel_run(run_dir)
    assert result["success"] is True
    assert 99999 in result["terminated_pids"]
    assert "worker-1" in result["checkpoints_cancelled"]
    # worker-2 already completed; should NOT be in cancelled
    assert "worker-2" not in result["checkpoints_cancelled"]


def test_cli_coord_cancel_unknown_run(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "cancel", "--run-id", "nope"])
    assert result.exit_code == 1


def test_cli_coord_cancel_happy(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_run(iso_path, "20260521T020202-bbcc", {
            "worker-1": {"state": "in_progress", "pid": 88888},
        })
        with patch("harness.coord.canceller._terminate_pid", return_value=True):
            result = runner.invoke(cli, [
                "coord", "cancel", "--run-id", "20260521T020202-bbcc",
            ])
    assert result.exit_code == 0, result.output
    assert "20260521T020202-bbcc" in result.output
    assert "1 pid(s) terminated" in result.output
