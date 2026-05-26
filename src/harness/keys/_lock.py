"""W14-KEYS-POOL-HARDENING 2026-05-26: cross-platform file lock helper.

Why not portalocker?
====================

The harness has a "no new deps unless absolutely necessary" policy.
File locking via stdlib is sufficient for our use case (single-machine,
single-operator coordination between Python processes that touch the
keys/health/policy files).

POSIX: ``fcntl.flock(fd, LOCK_EX)`` — exclusive lock; auto-released
when file descriptor closes.

Windows: ``msvcrt.locking(fd, LK_LOCK, length)`` — blocks waiting for
the lock; ``LK_LOCK`` retries automatically up to 10 attempts at 1s
intervals before raising ``OSError``.

Usage::

    from harness.keys._lock import locked_write

    with locked_write(path) as f:
        f.write("new contents\\n")
    # File auto-closed + unlocked when context exits.

For atomic write semantics, write to a ``.tmp`` sibling and ``replace``
into the final path *while still holding the lock*::

    with locked_write(path.with_suffix(".lock")) as _lock:
        # _lock is just a sentinel file; we hold its lock
        path.with_suffix(".tmp").write_text(new_content, encoding="utf-8")
        path.with_suffix(".tmp").replace(path)

The sentinel-lock pattern decouples "lock file" from "data file" so
the data file's content isn't truncated by the lock-open operation.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_IS_WINDOWS = sys.platform == "win32"


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an exclusive lock on ``lock_path``.

    ``lock_path`` is a *sentinel* file used purely for locking — its
    content is irrelevant.  Use a sibling of your data file (e.g.
    ``data.json`` → ``data.json.lock``).  The sentinel is created if
    missing.

    On contention:
      - POSIX: blocks until the holder releases (no timeout)
      - Windows: retries up to 10 times at 1-second intervals (msvcrt
        default), then raises OSError

    Best-effort: if the locking syscall itself fails for any reason,
    we log and continue without locking rather than block the
    operator's workflow.  Telemetry is not load-bearing.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Open with mode "a+" so we don't truncate; create if missing
    f = open(lock_path, "a+", encoding="utf-8")
    try:
        if _IS_WINDOWS:
            import msvcrt
            # Lock first byte (msvcrt requires a length).  LK_LOCK blocks
            # with retry; LK_NBLCK would be non-blocking.
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                locked = True
            except OSError:
                locked = False  # best-effort, continue without lock
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                locked = True
            except OSError:
                locked = False
        try:
            yield
        finally:
            if locked:
                if _IS_WINDOWS:
                    import msvcrt
                    try:
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
    finally:
        f.close()


def lock_path_for(data_path: Path) -> Path:
    """Return the sentinel-lock path for a given data file."""
    return data_path.with_suffix(data_path.suffix + ".lock")
