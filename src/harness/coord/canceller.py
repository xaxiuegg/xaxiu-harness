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
