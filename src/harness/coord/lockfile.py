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
