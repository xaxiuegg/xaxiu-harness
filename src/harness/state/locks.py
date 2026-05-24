"""W9-STATE-FILE-LOCK: stdlib-only advisory locks for shared state files.

M11 PROBLEM: ``engine_health.json`` (and the other JSON state files)
are mutated by multiple runtimes — ``ThreadPoolExecutor`` in
preflight, ``asyncio`` in coord, ``multiprocessing`` in mutation
sweeps — with zero cross-runtime synchronization.  A scheduled
``preflight --fix`` racing a manual one is the textbook data race
M11 called out.

W9 SOLUTION: a minimal context-manager that wraps the read-modify-
write cycle in an advisory file lock.  Stdlib-only so we don't drag
in ``portalocker`` as a new install-time dep (operator is
non-technical; avoiding extra pip surface).

Platforms:
    - Windows: ``msvcrt.locking`` LK_NBLCK / LK_UNLCK on a dedicated
      lockfile next to the target.
    - Unix: ``fcntl.flock`` LOCK_EX | LOCK_NB on the same.

Lock files (``<target>.lock``) are NOT cleaned up on process exit —
that's fine because the lock byte is released when the FD closes
even if the file persists.  This avoids an extra delete syscall
on every release.

Usage:
    from harness.state.locks import advisory_lock
    with advisory_lock(Path("state/engine_health.json"), timeout_sec=5):
        # read-modify-write cycle goes here
        ...
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path


class LockTimeoutError(Exception):
    """Raised when an advisory lock cannot be acquired within timeout_sec.

    Tag: ``L4.state.E_lock_timeout`` per the harness error taxonomy.
    """

    def __init__(self, lock_path: Path, timeout_sec: float) -> None:
        super().__init__(
            f"L4.state.E_lock_timeout: could not acquire {lock_path} "
            f"within {timeout_sec}s"
        )
        self.lock_path = lock_path
        self.timeout_sec = timeout_sec


def _is_windows() -> bool:
    return sys.platform == "win32"


def _lock_path_for(target: Path) -> Path:
    """``state/engine_health.json`` -> ``state/engine_health.json.lock``."""
    return target.with_suffix(target.suffix + ".lock")


@contextmanager
def advisory_lock(target: Path, *, timeout_sec: float = 5.0,
                  poll_interval_sec: float = 0.05):
    """Hold an advisory lock for the duration of the context.

    Re-tries acquisition every *poll_interval_sec* seconds until the
    lock is held or *timeout_sec* elapses (raises :class:`LockTimeoutError`
    in the latter case).  The lock is *advisory* — only callers that
    also use ``advisory_lock`` on the same target will be blocked.

    Args:
        target: The state file path being protected.
        timeout_sec: How long to wait for the lock before raising
            ``LockTimeoutError``.  Default 5s; the same budget the
            preflight checks use.
        poll_interval_sec: Sleep duration between retries.  50ms is a
            good default — fast enough that two contenders rarely
            both wait the full timeout, slow enough that CPU isn't
            pegged.
    """
    lock_path = _lock_path_for(target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Open the lock file (create if missing).  We keep the FD open
    # for the duration of the lock — releasing the FD releases the
    # lock byte on both platforms.
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout_sec
        held = False
        last_exc: BaseException | None = None
        while time.monotonic() < deadline:
            try:
                _try_lock(fd)
                held = True
                break
            except (OSError, IOError, BlockingIOError) as exc:
                last_exc = exc
                time.sleep(poll_interval_sec)
        if not held:
            os.close(fd)
            raise LockTimeoutError(lock_path, timeout_sec) from last_exc
        try:
            yield
        finally:
            try:
                _unlock(fd)
            except OSError:
                # Best-effort unlock; FD close below releases anyway
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _try_lock(fd: int) -> None:
    """Acquire an exclusive non-blocking lock on *fd*, raising on failure."""
    if _is_windows():
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    """Release the lock held on *fd*."""
    if _is_windows():
        import msvcrt
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
