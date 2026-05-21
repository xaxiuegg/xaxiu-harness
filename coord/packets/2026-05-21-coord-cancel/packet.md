# COORD-CANCEL — `harness coord cancel <run_id>` graceful in-flight stop

## Goal

Currently the only way to stop a running `harness coord run` mid-flight is
Ctrl-C (which leaves run_state in "running" and worker subprocesses
possibly alive).  Add a graceful cancel verb that:

1. Reads run_state.json + worker PIDs.
2. Sends terminate signals to live worker subprocesses.
3. Writes a `state="cancelled"` run_state + per-worker
   `state="cancelled"` checkpoint.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/coord/canceller.py`

```python
"""Graceful cancellation of an in-flight coord run."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from harness.coord.checkpoint import Checkpoint, read_checkpoint, write_checkpoint, now_iso
from harness.coord.run_state import read_run_state, write_run_state
from harness.coord.schemas import IntegratorStatus, RunStateLiteral


def _terminate_pid(pid: int) -> bool:
    """Best-effort terminate a process; True if it exited or wasn't running."""
    if pid <= 0:
        return True
    try:
        if os.name == "nt":
            # Windows: use taskkill since os.kill semantics differ
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, check=False, timeout=5,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def cancel_run(run_dir: Path) -> dict[str, Any]:
    """Cancel a run in-place; return a small summary dict.

    Looks up run_state.json + walks checkpoints/, terminating any
    worker subprocess whose PID is recorded and marking it cancelled.
    """
    run_dir = Path(run_dir)
    state = read_run_state(run_dir / "run_state.json")
    if state is None:
        return {"success": False, "error": "no run_state found"}

    terminated: list[int] = []
    checkpoints_cancelled: list[str] = []

    # Workers from run_state may carry pid in WorkerStatus
    for wid, wstatus in (state.workers or {}).items():
        pid = getattr(wstatus, "pid", None)
        if pid:
            if _terminate_pid(int(pid)):
                terminated.append(int(pid))
        ckpt_path = run_dir / "checkpoints" / f"{wid}.json"
        ckpt = read_checkpoint(ckpt_path)
        if ckpt is not None and ckpt.state in ("pending", "in_progress"):
            write_checkpoint(
                ckpt_path,
                ckpt.model_copy(update={"state": "failed", "tests_summary": "cancelled by operator"}),
            )
            checkpoints_cancelled.append(wid)

    # Mark run state cancelled (use FAILED literal — no CANCELLED in RunStateLiteral)
    state.state = RunStateLiteral.FAILED
    state.integrator_status = IntegratorStatus(
        state="failed",
        last_action="cancelled_by_operator",
        last_action_at=now_iso(),
    )
    write_run_state(run_dir / "run_state.json", state)

    return {
        "success": True,
        "run_id": state.run_id,
        "terminated_pids": terminated,
        "checkpoints_cancelled": checkpoints_cancelled,
    }
```

### 2. CLI subcommand

In `src/harness/cli.py`, find `@coord_group.command(name="cleanup")`.
Add NEW command IMMEDIATELY AFTER cleanup (or anywhere inside the
coord group):

```python
@coord_group.command(name="cancel")
@click.option("--run-id", required=True)
def coord_cancel(run_id: str) -> None:
    """Gracefully cancel an in-flight run: terminate workers + mark state cancelled."""
    from harness.coord.canceller import cancel_run
    run_dir = Path("runs") / run_id
    if not run_dir.exists():
        click.echo(f"error: no such run {run_id}", err=True)
        sys.exit(1)
    result = cancel_run(run_dir)
    if not result.get("success"):
        click.echo(f"error: {result.get('error','unknown')}", err=True)
        sys.exit(1)
    click.echo(
        f"cancelled run {result['run_id']}: "
        f"{len(result['terminated_pids'])} pid(s) terminated, "
        f"{len(result['checkpoints_cancelled'])} checkpoint(s) marked"
    )
```

### 3. Tests

`tests/test_coord_cancel.py`:

```python
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
```

## Acceptance

- `python -m pytest tests/test_coord_cancel.py` — green.
- Full suite stays green.
- `harness coord cancel --run-id <id>` exits 0 on success, 1 on missing run.

## Constraints

- DO NOT modify run_state.RunStateLiteral (we reuse FAILED since CANCELLED
  isn't in the literal; record cancellation reason in integrator_status).
- DO NOT touch worker.py or coordinator.py.
- _terminate_pid must be cross-platform (Windows taskkill / POSIX SIGTERM).
- Stdlib only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
