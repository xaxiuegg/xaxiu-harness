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
