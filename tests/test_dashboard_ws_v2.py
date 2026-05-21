"""Tests for v2 snapshot inclusion in dashboard WS broadcast."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_snapshot_includes_v2_runs(monkeypatch, tmp_path: Path) -> None:
    """_snapshot() exposes v2.runs from harness.dashboard.v2_routes.list_runs."""
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json", {
        "state": "running",
        "started_at": "2026-05-21T01:00:00Z",
        "last_tick_at": "2026-05-21T01:05:00Z",
    })
    _write(tmp_path / "runs" / "r1" / "plan.json", {
        "tasks": [{"worker_id": "worker-1"}],
    })

    from harness.dashboard.app import _snapshot
    snap = _snapshot()
    assert "v2" in snap
    assert isinstance(snap["v2"].get("runs"), list)
    assert any(r["run_id"] == "r1" for r in snap["v2"]["runs"])


def test_snapshot_includes_top_run_workers(monkeypatch, tmp_path: Path) -> None:
    """_snapshot().v2 includes per-worker detail for the most-recent run."""
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json", {
        "state": "running", "last_tick_at": "2026-05-21T01:05:00Z",
    })
    _write(tmp_path / "runs" / "r1" / "plan.json", {"tasks": []})
    _write(tmp_path / "runs" / "r1" / "checkpoints" / "worker-1.json", {
        "worker_id": "worker-1", "state": "completed",
        "files_modified": ["a.txt"], "commit_sha": "abc1234",
    })

    from harness.dashboard.app import _snapshot
    snap = _snapshot()
    workers = snap["v2"]["top_run_workers"]
    assert any(w["worker_id"] == "worker-1" for w in workers)


def test_snapshot_empty_when_no_runs(monkeypatch, tmp_path: Path) -> None:
    """_snapshot().v2.runs is an empty list when no runs/ dir exists."""
    monkeypatch.chdir(tmp_path)
    from harness.dashboard.app import _snapshot
    snap = _snapshot()
    assert snap["v2"]["runs"] == []
    assert snap["v2"]["top_run_workers"] == []
