# DASHBOARD-WS-V2-STREAM — extend WS snapshot to include v2 runs

## Goal

The dashboard's `/ws` endpoint pushes a snapshot every 5 seconds via
`harness.dashboard.app._snapshot()`.  Today that snapshot only includes
v1 state (engines, recent dispatches).  Operators using `harness coord
run` can't see live worker progress in the dashboard — they have to poll
the JSON `/v2/runs` endpoint manually.

This wave extends `_snapshot()` to include the same v2 telemetry that
`/v2/runs` and `/v2/runs/<id>/workers` expose, so the WebSocket stream
becomes a single source of truth.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. Extend `_snapshot()` in `src/harness/dashboard/app.py`

Find `def _snapshot(` in app.py (it returns a dict the WS broadcasts).
Add a `"v2"` key whose value is computed by calling the helpers from
`harness.dashboard.v2_routes`:

```python
# At top of file (after existing imports)
from harness.dashboard.v2_routes import list_runs as _list_runs

# Inside _snapshot(), before the return:
runs = _list_runs()
# Include a small per-run worker breakdown for the most-recently-touched run
top_run_workers: list[dict] = []
if runs:
    from harness.dashboard.v2_routes import list_workers as _list_workers
    top_run_id = max(
        (r for r in runs if r.get("last_tick_at")),
        key=lambda r: r["last_tick_at"],
        default=runs[0],
    )["run_id"]
    top_run_workers = _list_workers(top_run_id)

# Then add to the returned dict:
snapshot["v2"] = {
    "runs": runs,
    "top_run_workers": top_run_workers,
}
```

If the existing _snapshot function doesn't assign to a `snapshot` variable
before returning, refactor minimally — convert the return-dict-literal
into a `snapshot = { ... }` assignment + `snapshot["v2"] = ...` + `return
snapshot`.

### 2. Tests

New file `tests/test_dashboard_ws_v2.py`:

```python
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
```

## Acceptance

- `python -m pytest tests/test_dashboard_ws_v2.py` — all green.
- `python -m pytest --tb=short -q` — overall suite stays green.
- Manual: visit the dashboard while a coord run is in flight; the WS
  payload includes `v2.runs` and `v2.top_run_workers`.

## Constraints

- DO NOT modify `src/harness/dashboard/v2_routes.py`.
- DO NOT modify existing dashboard tests.
- The snapshot must REMAIN backwards-compatible — adding the `v2` key
  must not break any consumer reading the existing keys.

## Engine guidance

Tight scope: app.py edit + new test file.  Single backend.  Timeout 420s.
