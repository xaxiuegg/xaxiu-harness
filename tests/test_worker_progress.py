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
