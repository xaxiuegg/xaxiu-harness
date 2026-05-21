# COORD-LOG-STREAM — `harness coord watch <run_id>` live tail

## Goal

Operators need a way to watch a running coord run in real time without
running raw `Get-Content -Wait` on a wall of JSON files.  This wave adds
`harness coord watch <run_id>` — a foreground CLI verb that tails the
run's events and prints them human-readably.

## Scope (in-place edit; kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/coord/watch.py`

```python
"""Live-tail helpers for `harness coord watch`."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator


WATCH_POLL_SECONDS = 0.5


def _checkpoint_summary(ckpt_path: Path) -> dict | None:
    """Return a tiny dict describing the checkpoint, or None if unreadable."""
    try:
        data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "worker_id": data.get("worker_id"),
        "state": data.get("state"),
        "last_completed_step_id": data.get("last_completed_step_id"),
        "files_modified": data.get("files_modified") or [],
        "commit_sha": data.get("commit_sha"),
        "updated_at": data.get("updated_at"),
    }


def watch_run(run_dir: Path, *, poll_seconds: float = WATCH_POLL_SECONDS) -> Iterator[str]:
    """Yield human-readable event lines as the run progresses.

    Events come from:
      - run_state.json mtime changes      → "run_state -> <state>"
      - checkpoints/*.json mtime changes  → "worker-1: in_progress (step=s1)"
    Yields until the run state becomes terminal ('completed' / 'failed').
    """
    run_state_path = run_dir / "run_state.json"
    checkpoints_dir = run_dir / "checkpoints"

    last_state_mtime: float = 0.0
    last_ckpt_mtimes: dict[Path, float] = {}
    terminal_states = {"completed", "failed"}

    while True:
        # run_state change
        if run_state_path.exists():
            try:
                mtime = run_state_path.stat().st_mtime
            except OSError:
                mtime = last_state_mtime
            if mtime > last_state_mtime:
                last_state_mtime = mtime
                try:
                    data = json.loads(run_state_path.read_text(encoding="utf-8"))
                    state = data.get("state", "?")
                    yield f"run_state -> {state}"
                    if state in terminal_states:
                        return
                except (OSError, json.JSONDecodeError):
                    pass

        # checkpoint changes
        if checkpoints_dir.exists():
            for ckpt_path in sorted(checkpoints_dir.glob("*.json")):
                try:
                    mtime = ckpt_path.stat().st_mtime
                except OSError:
                    continue
                if mtime > last_ckpt_mtimes.get(ckpt_path, 0.0):
                    last_ckpt_mtimes[ckpt_path] = mtime
                    summary = _checkpoint_summary(ckpt_path)
                    if summary:
                        files = (
                            f" files={len(summary['files_modified'])}"
                            if summary.get("files_modified")
                            else ""
                        )
                        step = (
                            f" step={summary['last_completed_step_id']}"
                            if summary.get("last_completed_step_id")
                            else ""
                        )
                        yield (
                            f"{summary['worker_id']}: {summary['state']}{step}{files}"
                        )

        time.sleep(poll_seconds)
```

### 2. Wire into `cli.py` — new `coord watch` subcommand

Locate `@coord_group.command(name="status")` (search for that string).
Add a NEW command immediately AFTER `coord_status`:

```python
@coord_group.command(name="watch")
@click.option("--run-id", required=True)
@click.option("--max-seconds", default=None, type=int,
              help="Stop watching after N seconds even if run is still active.")
def coord_watch(run_id: str, max_seconds: int | None) -> None:
    """Tail a running coord run and print events as they land."""
    import time as _time
    from harness.coord.watch import watch_run

    run_dir = Path("runs") / run_id
    if not run_dir.exists():
        click.echo(f"error: no such run {run_id}", err=True)
        sys.exit(1)

    deadline = _time.monotonic() + max_seconds if max_seconds else None
    try:
        for event in watch_run(run_dir):
            click.echo(event)
            if deadline and _time.monotonic() > deadline:
                click.echo("watch: max-seconds reached", err=True)
                break
    except KeyboardInterrupt:
        click.echo("watch: interrupted", err=True)
```

### 3. Tests

New file `tests/test_coord_watch.py`:

```python
"""Tests for harness.coord.watch."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from harness.coord.watch import watch_run, _checkpoint_summary


def test_checkpoint_summary_returns_none_on_missing(tmp_path: Path) -> None:
    assert _checkpoint_summary(tmp_path / "nope.json") is None


def test_checkpoint_summary_returns_none_on_broken_json(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    p.write_text("not json", encoding="utf-8")
    assert _checkpoint_summary(p) is None


def test_checkpoint_summary_extracts_expected_keys(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    p.write_text(json.dumps({
        "worker_id": "worker-1",
        "state": "completed",
        "last_completed_step_id": "s1",
        "files_modified": ["a.txt", "b.txt"],
        "commit_sha": "abc1234",
        "updated_at": "2026-05-21T00:00:00Z",
    }), encoding="utf-8")
    s = _checkpoint_summary(p)
    assert s == {
        "worker_id": "worker-1",
        "state": "completed",
        "last_completed_step_id": "s1",
        "files_modified": ["a.txt", "b.txt"],
        "commit_sha": "abc1234",
        "updated_at": "2026-05-21T00:00:00Z",
    }


def test_watch_run_yields_run_state_then_terminates(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "test-run"
    run_dir.mkdir(parents=True)

    # Run watch_run in a thread; have main thread mutate run_state.json
    events: list[str] = []
    stop_event = threading.Event()

    def driver() -> None:
        time.sleep(0.1)
        (run_dir / "run_state.json").write_text(
            json.dumps({"state": "running"}), encoding="utf-8"
        )
        time.sleep(0.2)
        (run_dir / "run_state.json").write_text(
            json.dumps({"state": "completed"}), encoding="utf-8"
        )

    threading.Thread(target=driver, daemon=True).start()

    deadline = time.monotonic() + 3.0
    for event in watch_run(run_dir, poll_seconds=0.05):
        events.append(event)
        if time.monotonic() > deadline:
            break
    assert any("run_state -> running" in e for e in events), events
    assert any("run_state -> completed" in e for e in events), events


def test_watch_run_yields_checkpoint_changes(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "test-run"
    (run_dir / "checkpoints").mkdir(parents=True)
    ckpt = run_dir / "checkpoints" / "worker-1.json"

    def driver() -> None:
        time.sleep(0.1)
        ckpt.write_text(json.dumps({
            "worker_id": "worker-1", "state": "in_progress",
            "last_completed_step_id": "s1", "files_modified": ["x.txt"],
        }), encoding="utf-8")
        time.sleep(0.15)
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
    assert any("worker-1: in_progress" in e for e in events), events
```

## Acceptance

- `python -m pytest tests/test_coord_watch.py` — all green.
- `python -m pytest --tb=short -q` — overall suite stays green.
- `harness coord watch --help` shows the new command.
- Manual: `harness coord watch --run-id 20260521T000000-aabb --max-seconds 5`
  prints `run_state -> ...` and `worker-N: ...` lines, exits on terminal state
  or after 5 seconds.

## Constraints

- Do NOT touch tests/test_coord_cli.py (just add the new test_coord_watch.py).
- Do NOT touch other coord modules (planner/coordinator/worker/integrator).
- Keep watch.py under 100 LOC.
- Use stdlib only — no new dependencies, no asyncio.

## Engine guidance

Tight scope: 1 new module + 1 CLI command + 1 test file.  swarm/kimi or
swarm/kimi-api works.  Timeout 420s.
