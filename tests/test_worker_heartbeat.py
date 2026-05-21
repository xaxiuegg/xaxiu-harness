"""Tests for WORKER-HEARTBEAT — _heartbeat_touch + detect_stalled_workers."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.coord.worker import _heartbeat_touch
from harness.coord.coordinator import detect_stalled_workers
from harness.coord.checkpoint import Checkpoint, write_checkpoint


def test_heartbeat_touch_creates_sentinel(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    _heartbeat_touch(run_dir, "worker-1")
    p = run_dir / "checkpoints" / "worker-1.heartbeat"
    assert p.exists()


def test_heartbeat_touch_updates_mtime(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    _heartbeat_touch(run_dir, "worker-1")
    p = run_dir / "checkpoints" / "worker-1.heartbeat"
    mtime1 = p.stat().st_mtime
    # Force old mtime, then re-touch
    old = mtime1 - 1000
    os.utime(p, (old, old))
    _heartbeat_touch(run_dir, "worker-1")
    mtime2 = p.stat().st_mtime
    assert mtime2 > old


def test_heartbeat_touch_swallows_errors(tmp_path: Path) -> None:
    # Pointing at a path under a file (can't create dirs) should not raise.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    _heartbeat_touch(blocker / "deep", "worker-1")  # must not raise


def test_detect_stalled_empty_when_no_checkpoints(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    assert detect_stalled_workers(run_dir) == []


def test_detect_stalled_ignores_completed(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    (run_dir / "checkpoints").mkdir(parents=True)
    write_checkpoint(
        run_dir / "checkpoints" / "worker-1.json",
        Checkpoint(worker_id="worker-1", run_id="r1", state="completed"),
    )
    # No heartbeat file, but state is completed → not stalled
    assert detect_stalled_workers(run_dir, max_silence_seconds=1) == []


def test_detect_stalled_flags_old_heartbeat(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    (run_dir / "checkpoints").mkdir(parents=True)
    write_checkpoint(
        run_dir / "checkpoints" / "worker-1.json",
        Checkpoint(worker_id="worker-1", run_id="r1", state="in_progress"),
    )
    hb = run_dir / "checkpoints" / "worker-1.heartbeat"
    hb.touch()
    # Force heartbeat mtime far in the past
    old = time.time() - 7200  # 2 hours ago
    os.utime(hb, (old, old))
    stalled = detect_stalled_workers(run_dir, max_silence_seconds=600)
    assert stalled == ["worker-1"]


def test_detect_stalled_skips_recent_heartbeat(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    (run_dir / "checkpoints").mkdir(parents=True)
    write_checkpoint(
        run_dir / "checkpoints" / "worker-1.json",
        Checkpoint(worker_id="worker-1", run_id="r1", state="in_progress"),
    )
    (run_dir / "checkpoints" / "worker-1.heartbeat").touch()  # fresh
    assert detect_stalled_workers(run_dir, max_silence_seconds=600) == []
