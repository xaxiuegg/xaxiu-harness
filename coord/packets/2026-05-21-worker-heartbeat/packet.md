# WORKER-HEARTBEAT — per-step liveness pulse for hang detection

## Goal

The worker currently writes step_start/step_done events to
`checkpoints/<wid>.progress.jsonl` (WORKER-PROGRESS-STREAM).  Add a
finer-grained heartbeat — a single mtime touch on a sentinel file every
N seconds during a long dispatch — so the coordinator can detect a
hung worker subprocess and surface it as an L4 stall flag.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/coord/worker.py`

ADD near the existing `_append_progress` helper:

```python
def _heartbeat_touch(run_dir: Path, worker_id: str) -> None:
    """Update mtime on checkpoints/<wid>.heartbeat sentinel.  Best-effort."""
    try:
        hb_path = run_dir / "checkpoints" / f"{worker_id}.heartbeat"
        hb_path.parent.mkdir(parents=True, exist_ok=True)
        hb_path.touch(exist_ok=True)
        # Force mtime update even if file existed
        import os, time
        now = time.time()
        os.utime(hb_path, (now, now))
    except Exception:
        pass
```

### 2. Wire heartbeat touches at step boundaries

Inside `run_worker`, find the step-execution `for` loop.  Add a
`_heartbeat_touch(run_dir, task_obj.worker_id)` call:

a) Right at the TOP of the for-body (before `_append_progress(step_start)`):

```python
        _heartbeat_touch(run_dir, task_obj.worker_id)
```

b) Right BEFORE `result = dispatch_packet(...)` (before the engine call,
   so the heartbeat is fresh even if the call blocks for minutes):

```python
        _heartbeat_touch(run_dir, task_obj.worker_id)
```

c) After the dispatch returns (success or not):

```python
        _heartbeat_touch(run_dir, task_obj.worker_id)
```

### 3. New helper in `src/harness/coord/coordinator.py` — stall detection

ADD a new top-level function (outside any class):

```python
def detect_stalled_workers(
    run_dir: Path,
    *,
    max_silence_seconds: int = 600,
    now: datetime | None = None,
) -> list[str]:
    """Return worker_ids whose heartbeat file is older than max_silence_seconds.

    A missing heartbeat is treated as "no heartbeat yet" — only counts as
    stalled if the corresponding checkpoint is state="in_progress".
    """
    import time
    from datetime import datetime, timezone
    from harness.coord.checkpoint import read_checkpoint

    now_dt = now or datetime.now(timezone.utc)
    stalled: list[str] = []
    ckpt_dir = run_dir / "checkpoints"
    if not ckpt_dir.exists():
        return stalled

    for ckpt_path in sorted(ckpt_dir.glob("*.json")):
        ckpt = read_checkpoint(ckpt_path)
        if ckpt is None or ckpt.state != "in_progress":
            continue
        hb_path = ckpt_dir / f"{ckpt.worker_id}.heartbeat"
        if not hb_path.exists():
            # No heartbeat yet — count as stalled only if checkpoint is
            # also older than the silence window (otherwise it might just
            # have just started)
            try:
                age = now_dt.timestamp() - ckpt_path.stat().st_mtime
            except OSError:
                age = 0
            if age > max_silence_seconds:
                stalled.append(ckpt.worker_id)
            continue
        try:
            hb_age = now_dt.timestamp() - hb_path.stat().st_mtime
        except OSError:
            continue
        if hb_age > max_silence_seconds:
            stalled.append(ckpt.worker_id)
    return stalled
```

### 4. Tests

New file `tests/test_worker_heartbeat.py`:

```python
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
```

## Acceptance

- `python -m pytest tests/test_worker_heartbeat.py` — green.
- Full suite stays green (worker tests + coordinator tests must keep passing).

## Constraints

- DO NOT modify the existing checkpoint or progress jsonl write paths.
- _heartbeat_touch must NEVER raise.
- detect_stalled_workers is read-only.
- Stdlib only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
