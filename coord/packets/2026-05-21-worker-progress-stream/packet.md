# WORKER-PROGRESS-STREAM — step-level progress jsonl

## Goal

Long Kimi steps inside `worker.run_worker` currently appear stalled to the
operator — checkpoints are only written AFTER each step completes.  Add a
progressive jsonl event stream that the worker appends to as it starts /
finishes each step, so `harness coord watch` (and the dashboard WS) can
show live step transitions.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/coord/worker.py`

ADD this helper near the top of worker.py (right after the imports and
existing helper functions):

```python
def _append_progress(run_dir: Path, worker_id: str, event: dict) -> None:
    """Atomically append a progress event to checkpoints/<worker_id>.progress.jsonl.

    Best-effort — never raises (worker steps must not fail on telemetry I/O).
    """
    try:
        progress_path = run_dir / "checkpoints" / f"{worker_id}.progress.jsonl"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": now_iso(), **event}, ensure_ascii=False)
        with open(progress_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
```

### 2. Wire into `run_worker`

Find the step-execution loop inside `run_worker` (search for
`for idx in range(start_idx, len(task_obj.steps)):`).

At the TOP of the for-body (right after `step = task_obj.steps[idx]`),
add:

```python
        _append_progress(run_dir, task_obj.worker_id, {
            "event": "step_start", "step_id": step.step_id,
            "kind": step.kind, "idx": idx,
        })
```

At the BOTTOM of the for-body (right after
`write_checkpoint(checkpoint_path, ckpt)`), add:

```python
        _append_progress(run_dir, task_obj.worker_id, {
            "event": "step_done", "step_id": step.step_id,
            "files_modified": list(ckpt.files_modified or []),
        })
```

Right after the final `write_checkpoint(checkpoint_path, ckpt)` (the one
that writes the final state — outside the loop), add:

```python
    _append_progress(run_dir, task_obj.worker_id, {
        "event": "worker_done", "state": final_state,
        "tests_passed": tests["failed"] == 0,
    })
```

### 3. Extend `harness.coord.watch.watch_run` to surface progress events

In `src/harness/coord/watch.py`, find the for-loop that walks
`checkpoints_dir.glob("*.json")`.  AFTER that loop, add a second loop
walking `*.progress.jsonl`:

```python
        # progress event tails
        if checkpoints_dir.exists():
            for prog_path in sorted(checkpoints_dir.glob("*.progress.jsonl")):
                try:
                    mtime = prog_path.stat().st_mtime
                except OSError:
                    continue
                if mtime > last_progress_mtimes.get(prog_path, 0.0):
                    # Read new lines since last position
                    last_pos = last_progress_pos.get(prog_path, 0)
                    try:
                        with open(prog_path, "r", encoding="utf-8") as f:
                            f.seek(last_pos)
                            new_text = f.read()
                            last_progress_pos[prog_path] = f.tell()
                    except OSError:
                        continue
                    last_progress_mtimes[prog_path] = mtime
                    for line in new_text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        worker_id = prog_path.stem.replace(".progress", "")
                        yield f"{worker_id}: {ev.get('event','?')} step={ev.get('step_id','-')}"
```

Initialize `last_progress_mtimes: dict[Path, float] = {}` and
`last_progress_pos: dict[Path, int] = {}` at the top of `watch_run` next
to `last_ckpt_mtimes`.

### 4. Tests

`tests/test_worker_progress.py`:

```python
"""Tests for WORKER-PROGRESS-STREAM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.coord.worker import _append_progress


def test_append_progress_creates_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    _append_progress(run_dir, "worker-1", {"event": "step_start", "step_id": "s1"})
    p = run_dir / "checkpoints" / "worker-1.progress.jsonl"
    assert p.exists()
    line = p.read_text(encoding="utf-8").strip()
    data = json.loads(line)
    assert data["event"] == "step_start"
    assert data["step_id"] == "s1"
    assert "ts" in data


def test_append_progress_appends_multiple(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    _append_progress(run_dir, "worker-1", {"event": "step_start", "step_id": "s1"})
    _append_progress(run_dir, "worker-1", {"event": "step_done", "step_id": "s1"})
    p = run_dir / "checkpoints" / "worker-1.progress.jsonl"
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2


def test_append_progress_swallows_errors(tmp_path: Path) -> None:
    """Best-effort: writing into a non-writable location does not raise."""
    # Point at a file path that can't be created (parent is a regular file)
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    fake_run = blocker / "deep"
    # Should NOT raise
    _append_progress(fake_run, "worker-1", {"event": "step_start"})


def test_watch_run_yields_progress_events(tmp_path: Path) -> None:
    """watch_run picks up new lines from checkpoints/<id>.progress.jsonl."""
    import threading, time
    from harness.coord.watch import watch_run

    run_dir = tmp_path / "runs" / "r1"
    (run_dir / "checkpoints").mkdir(parents=True)
    progress = run_dir / "checkpoints" / "worker-1.progress.jsonl"

    def driver() -> None:
        time.sleep(0.05)
        progress.write_text(json.dumps({
            "ts": "t1", "event": "step_start", "step_id": "s1", "kind": "edit", "idx": 0
        }) + "\n", encoding="utf-8")
        time.sleep(0.1)
        (run_dir / "run_state.json").write_text(
            json.dumps({"state": "completed"}), encoding="utf-8"
        )

    threading.Thread(target=driver, daemon=True).start()
    events: list[str] = []
    deadline = time.monotonic() + 3.0
    for event in watch_run(run_dir, poll_seconds=0.05):
        events.append(event)
        if time.monotonic() > deadline:
            break
    assert any("worker-1" in e and "step_start" in e for e in events), events
```

## Acceptance

- `python -m pytest tests/test_worker_progress.py` — green.
- Full suite stays green (especially test_coord_watch.py + test_coord_worker.py).

## Constraints

- DO NOT modify the existing checkpoint write path.
- DO NOT touch test files other than the new one + (if needed) the watch
  test to accommodate the new event format — but only if the watch test
  is failing; add new tests instead.
- _append_progress must NEVER raise — wrap everything in try/except.
- Stdlib only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
