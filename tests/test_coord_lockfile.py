"""Tests for LOCK-COORD-DIR — file_lock context manager."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from harness.coord.lockfile import file_lock, _lock_path_for, _is_lock_stale


def test_lock_path_for_appends_lock_suffix(tmp_path: Path) -> None:
    target = tmp_path / "STATUS.csv"
    lock = _lock_path_for(target)
    assert lock.name == "STATUS.csv.lock"


def test_file_lock_first_acquire_succeeds(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    with file_lock(target) as ok:
        assert ok is True
        # Lock file exists during the block
        assert _lock_path_for(target).exists()
    # Lock file is cleaned up after the block
    assert not _lock_path_for(target).exists()


def test_file_lock_second_acquire_times_out(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    # Acquire and HOLD via a background thread
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with file_lock(target, timeout=10.0) as ok:
            assert ok
            holding.set()
            release.wait(timeout=5.0)

    t = threading.Thread(target=hold, daemon=True)
    t.start()
    holding.wait(timeout=5.0)
    # Now try to acquire with a tiny timeout — should time out and yield False
    try:
        with file_lock(target, timeout=0.5) as ok:
            assert ok is False
    finally:
        release.set()
        t.join(timeout=5.0)


def test_file_lock_stale_lock_is_stolen(tmp_path: Path) -> None:
    """A lock file older than 30s is considered abandoned and reacquired."""
    target = tmp_path / "x.txt"
    lock_path = _lock_path_for(target)
    lock_path.write_text("12345")
    # Force the lock's mtime to far in the past
    old = time.time() - 1000
    os.utime(lock_path, (old, old))
    with file_lock(target, timeout=2.0) as ok:
        assert ok is True


def test_is_lock_stale_handles_missing(tmp_path: Path) -> None:
    assert _is_lock_stale(tmp_path / "nope.lock") is False
