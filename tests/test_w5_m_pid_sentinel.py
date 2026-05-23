"""W5-M: PID-sentinel duplicate-worker-spawn prevention.

Path 2 pilot caught the worker race: `coord run --watch` re-instantiates
Coordinator each tick, so `_procs` (the in-process tracking map) is
empty on each new tick.  The coordinator then re-spawns the same
worker as a fresh subprocess.  Both subprocesses race on the same
worktree — one applies the edit, the other sees the SEARCH no longer
matches → W4-A misfires as silent_no_op.

W5-M adds a disk-based PID sentinel.  Before spawning, read
`<worker_id>.pid` and probe the pid with `os.kill(pid, 0)`.  Skip
spawn if the pid is alive.

These tests pin the helper's contract (live + dead + missing + malformed
pid sentinel behaviour) without spinning up real subprocesses.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.coord.coordinator import _worker_pid_alive


def test_missing_pid_file_returns_false(tmp_path: Path) -> None:
    """No pid file → not alive (allow spawn)."""
    assert _worker_pid_alive(tmp_path / "worker-1.pid") is False


def test_malformed_pid_file_returns_false(tmp_path: Path) -> None:
    """Garbage in pid file → not alive (allow spawn, don't crash)."""
    pid_path = tmp_path / "worker-1.pid"
    pid_path.write_text("not-a-pid", encoding="utf-8")
    assert _worker_pid_alive(pid_path) is False


def test_empty_pid_file_returns_false(tmp_path: Path) -> None:
    pid_path = tmp_path / "worker-1.pid"
    pid_path.write_text("", encoding="utf-8")
    assert _worker_pid_alive(pid_path) is False


def test_negative_pid_returns_false(tmp_path: Path) -> None:
    pid_path = tmp_path / "worker-1.pid"
    pid_path.write_text("-99", encoding="utf-8")
    assert _worker_pid_alive(pid_path) is False


def test_zero_pid_returns_false(tmp_path: Path) -> None:
    """pid 0 is a special signal-broadcast value; never a real process."""
    pid_path = tmp_path / "worker-1.pid"
    pid_path.write_text("0", encoding="utf-8")
    assert _worker_pid_alive(pid_path) is False


def test_definitely_dead_pid_returns_false(tmp_path: Path) -> None:
    """A very-high pid that doesn't exist on the system → false."""
    pid_path = tmp_path / "worker-1.pid"
    # Pick a pid likely to be invalid: 2^31 - 7 (huge, well past any real pid)
    pid_path.write_text(str(2_147_483_641), encoding="utf-8")
    assert _worker_pid_alive(pid_path) is False


def test_current_process_pid_returns_true(tmp_path: Path) -> None:
    """Our own pid is always alive (we're running this test)."""
    pid_path = tmp_path / "worker-1.pid"
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    assert _worker_pid_alive(pid_path) is True


def test_pid_file_with_trailing_whitespace(tmp_path: Path) -> None:
    """Pid sentinel may have stray whitespace from text editors / Windows."""
    pid_path = tmp_path / "worker-1.pid"
    pid_path.write_text(f"  {os.getpid()}  \n", encoding="utf-8")
    assert _worker_pid_alive(pid_path) is True
