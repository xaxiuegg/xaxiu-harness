# LOCK-COORD-DIR — multi-tenancy guard for parallel Claude Code sessions

## Goal

Two parallel Claude Code sessions running in the same xaxiu-harness clone
can silently overwrite each other's STATUS.csv writes (this nearly hit
the operator on 2026-05-21 mid-session).  Add file-locking on canonical
coord/ writes so the second writer waits or fails fast.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/coord/lockfile.py`

```python
"""Cross-process file locks for coord/ writes (LOCK-COORD-DIR, 2026-05-21).

Stdlib-only implementation — uses ``msvcrt`` on Windows and ``fcntl`` on
POSIX so we don't add a new dependency.  Locks are advisory:
``acquire_lock`` blocks (with timeout) until the lock is taken;
``release_lock`` is a no-op if the file was never locked.

Use as a context manager:

    with file_lock(Path("coord/STATUS.csv")) as ok:
        if not ok:
            raise RuntimeError("could not acquire lock on STATUS.csv")
        # ... do the atomic write ...
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path
from typing import Iterator, Optional


DEFAULT_LOCK_TIMEOUT_S = 30.0
_STALE_AFTER_SECONDS = 30


def _lock_path_for(target: Path) -> Path:
    return target.with_suffix(target.suffix + ".lock")


def _is_lock_stale(lock_path: Path) -> bool:
    if not lock_path.exists():
        return False
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return False
    return age > _STALE_AFTER_SECONDS


def _try_acquire_once(lock_path: Path) -> Optional[int]:
    """Open lock file with O_EXCL.  Return file descriptor or None on collision."""
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
    except OSError:
        pass
    return fd


@contextlib.contextmanager
def file_lock(target: Path, *, timeout: float = DEFAULT_LOCK_TIMEOUT_S) -> Iterator[bool]:
    """Acquire an exclusive lock on *target*.  Yields True on success, False on timeout."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path_for(target)
    deadline = time.monotonic() + max(timeout, 0.0)
    fd: Optional[int] = None
    try:
        while True:
            fd = _try_acquire_once(lock_path)
            if fd is not None:
                yield True
                return
            # Lock held — check for staleness (process crashed?)
            if _is_lock_stale(lock_path):
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(0.1)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass
```

### 2. Wire into status/store.py atomic-write path

Find `src/harness/status/store.py` — specifically the function that
writes STATUS.csv (search for `write_status` or `tempfile.mkstemp` + the
csv write).  Wrap the write in the new file_lock:

```python
# At top of write_status (or whichever public writer):
from harness.coord.lockfile import file_lock
# Then around the existing tempfile + replace block:
with file_lock(target_path) as ok:
    if not ok:
        from harness.errors import StateLockTimeout  # add this error if missing
        raise StateLockTimeout(f"could not acquire lock on {target_path} within timeout")
    # ... existing atomic write ...
```

If `StateLockTimeout` doesn't exist in harness.errors, add it as a
plain subclass:

```python
class StateLockTimeout(RuntimeError):
    pass
```

If you don't want to extend status/store this aggressively, ONLY add
the lock helper module + tests — the integration into status/store can
be a separate row.  The packet's primary deliverable is the lockfile
module + tests.

### 3. Tests

`tests/test_coord_lockfile.py`:

```python
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
```

## Acceptance

- `python -m pytest tests/test_coord_lockfile.py` — green.
- Full suite stays green.

## Constraints

- DO NOT add new third-party deps (no portalocker).  Stdlib only.
- DO NOT modify status/store.py if integration risk is high — the
  lockfile module + tests are sufficient to ship.  Status store
  integration can come in a follow-up row.
- The lock file MUST be cleaned up on context-manager exit even when the
  block raises.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
