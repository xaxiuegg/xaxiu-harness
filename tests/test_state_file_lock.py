"""W9-STATE-FILE-LOCK: tests for the advisory-lock helper + integration.

M11 PROBLEM: engine_health.json is shared mutable state across
ThreadPoolExecutor (preflight), asyncio (coord), and multiprocessing
(mutation sweeps) with no synchronization.  A scheduled preflight
--fix racing a manual one is the textbook lost-update race.

W9 SOLUTION: stdlib-only advisory lock (msvcrt on Windows, fcntl on
Unix) wrapped around the read-modify-write sites.
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from harness.state.locks import (
    LockTimeoutError,
    advisory_lock,
    _lock_path_for,
)


# -- Lock-file path resolution --------------------------------------------


def test_lock_path_for_appends_lock_suffix(tmp_path):
    target = tmp_path / "engine_health.json"
    assert _lock_path_for(target) == tmp_path / "engine_health.json.lock"


def test_lock_path_for_handles_no_extension(tmp_path):
    target = tmp_path / "thing"
    assert _lock_path_for(target).name == "thing.lock"


# -- Single-process lock acquisition --------------------------------------


def test_advisory_lock_acquires_and_releases(tmp_path):
    target = tmp_path / "state.json"
    with advisory_lock(target, timeout_sec=2.0):
        # Lock file should exist while held
        assert (tmp_path / "state.json.lock").exists()
    # File still exists after release (we don't delete it)
    assert (tmp_path / "state.json.lock").exists()


def test_advisory_lock_creates_parent_dir(tmp_path):
    target = tmp_path / "subdir" / "state.json"
    with advisory_lock(target, timeout_sec=2.0):
        pass
    assert (tmp_path / "subdir").is_dir()


def test_advisory_lock_yields_for_use(tmp_path):
    """Verify the context manager protocol actually yields control."""
    target = tmp_path / "state.json"
    sentinel = {"entered": False}
    with advisory_lock(target, timeout_sec=2.0):
        sentinel["entered"] = True
    assert sentinel["entered"]


# -- Concurrent acquisition (threads) -------------------------------------


def test_concurrent_threads_serialize(tmp_path):
    """Two threads acquiring the same lock should serialize (not deadlock).

    Without the lock, both would enter the critical section
    simultaneously.  With it, one waits for the other.
    """
    target = tmp_path / "state.json"
    log: list[tuple[str, float]] = []

    def _worker(label: str):
        t = time.monotonic()
        with advisory_lock(target, timeout_sec=10.0,
                           poll_interval_sec=0.02):
            log.append((f"{label}-enter", time.monotonic() - t))
            time.sleep(0.2)  # critical section duration
            log.append((f"{label}-exit", time.monotonic() - t))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_worker, "A"), pool.submit(_worker, "B")]
        for f in as_completed(futures):
            f.result()

    # Extract just labels in order
    ordering = [entry[0] for entry in log]
    # Must see one full pair (A-enter, A-exit) before the other
    # (B-enter, B-exit) — not interleaved
    assert ordering in (
        ["A-enter", "A-exit", "B-enter", "B-exit"],
        ["B-enter", "B-exit", "A-enter", "A-exit"],
    ), f"Critical sections interleaved: {ordering}"


def test_concurrent_acquisition_times_out_when_held(tmp_path):
    """If one thread holds the lock past timeout, the second raises
    LockTimeoutError rather than hanging."""
    target = tmp_path / "state.json"
    started_a = threading.Event()
    release_a = threading.Event()
    timed_out = threading.Event()

    def _holder():
        with advisory_lock(target, timeout_sec=10.0):
            started_a.set()
            release_a.wait(timeout=3.0)

    def _waiter():
        started_a.wait(timeout=2.0)
        try:
            with advisory_lock(target, timeout_sec=0.5):
                pass
        except LockTimeoutError:
            timed_out.set()

    holder_t = threading.Thread(target=_holder)
    waiter_t = threading.Thread(target=_waiter)
    holder_t.start()
    waiter_t.start()

    waiter_t.join(timeout=3.0)
    release_a.set()
    holder_t.join(timeout=2.0)

    assert timed_out.is_set(), "Waiter should have hit LockTimeoutError"


def test_lock_timeout_error_carries_path_and_duration(tmp_path):
    """The exception's attributes are introspectable for operator log."""
    err = LockTimeoutError(tmp_path / "x.lock", 5.0)
    assert err.lock_path == tmp_path / "x.lock"
    assert err.timeout_sec == 5.0
    assert "5" in str(err)
    assert "E_lock_timeout" in str(err)


def test_lock_released_after_inner_exception(tmp_path):
    """If the locked code raises, the lock must still be released so
    a subsequent acquirer doesn't time out."""
    target = tmp_path / "state.json"

    with pytest.raises(RuntimeError, match="boom"):
        with advisory_lock(target, timeout_sec=2.0):
            raise RuntimeError("boom")

    # Subsequent acquirer should succeed quickly
    started = time.monotonic()
    with advisory_lock(target, timeout_sec=2.0):
        pass
    elapsed = time.monotonic() - started
    # Should be near-instant if lock was released
    assert elapsed < 0.5, (
        f"Re-acquire after exception took {elapsed:.2f}s — lock not "
        f"released properly."
    )


# -- Integration: preflight.fix_dead_engines uses the lock ----------------


def test_fix_dead_engines_uses_advisory_lock(tmp_path, monkeypatch):
    """preflight.fix_dead_engines should hold the engine_health lock
    for the duration of its writes (W9 integration)."""
    from harness import preflight
    from harness.state import files as state_files

    # Stub the dead-engines list to return one entry
    monkeypatch.setattr(
        "harness.engine_alarm.dead_engines",
        lambda: {"kimi": {"failures": 5, "last_failure": "2026-05-24"}},
    )

    # Redirect ENGINE_HEALTH_PATH to tmp_path
    monkeypatch.setattr(state_files, "ENGINE_HEALTH_PATH",
                        tmp_path / "engine_health.json")
    # Stub the update so we can capture invocation order
    updates: list[tuple[str, dict]] = []

    def _capture_update(engine, fields):
        updates.append((engine, fields))

    monkeypatch.setattr(state_files, "update_engine_health", _capture_update)

    # Spy on the lock: assert it was acquired before the first update
    from harness.state import locks as _locks
    lock_acquired = []
    original_lock = _locks.advisory_lock

    def _spy_lock(target, **kw):
        lock_acquired.append(str(target))
        return original_lock(target, **kw)

    monkeypatch.setattr("harness.preflight.state_files", state_files,
                        raising=False)
    # The preflight module imports advisory_lock via state.locks; patch
    # the import within preflight by patching state.locks.advisory_lock.
    monkeypatch.setattr("harness.state.locks.advisory_lock", _spy_lock)

    out = preflight.fix_dead_engines(dry_run=False)

    # Lock acquired for the engine_health path
    assert lock_acquired, "fix_dead_engines did not acquire the lock"
    assert "engine_health" in lock_acquired[0]
    # Quarantine update went through
    assert updates, "no engine_health update happened"
    assert updates[0][0] == "kimi"
    assert updates[0][1]["status"] == "quarantined"
    # Outcome looks healthy
    assert out.applied is True or out.name == "dead_engines"


def test_fix_dead_engines_surfaces_lock_timeout_to_operator(tmp_path, monkeypatch):
    """If another process holds the lock past timeout, the operator
    sees a plain-language 'try again' message, not a Python traceback."""
    from harness import preflight
    from harness.state import files as state_files

    monkeypatch.setattr(
        "harness.engine_alarm.dead_engines",
        lambda: {"kimi": {"failures": 5}},
    )
    monkeypatch.setattr(state_files, "ENGINE_HEALTH_PATH",
                        tmp_path / "engine_health.json")
    # Stub update so it doesn't actually touch disk
    monkeypatch.setattr(state_files, "update_engine_health",
                        lambda e, f: None)

    # Force the lock to always time out
    from contextlib import contextmanager

    @contextmanager
    def _timeout_lock(target, **kw):
        raise LockTimeoutError(target.with_suffix(target.suffix + ".lock"),
                                kw.get("timeout_sec", 5.0))
        yield  # unreachable

    monkeypatch.setattr("harness.state.locks.advisory_lock", _timeout_lock)

    out = preflight.fix_dead_engines(dry_run=False)
    assert out.applied is False
    assert "lock" in out.message.lower() or "already running" in out.message.lower()
    # Plain-language: no Python traceback in the message
    assert "Traceback" not in out.message
