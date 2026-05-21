# DASHBOARD-V2-ROUTES — read-only v2 telemetry endpoints

## Goal

Add three read-only JSON endpoints to the existing dashboard
(`src/harness/dashboard/app.py`) so the operator can introspect v2 runs,
workers, and proxy state via HTTP/WebSocket without poking at jsonl files.

Scope is JSON-only — no HTML/UI changes.  A subsequent UI wave can
consume these endpoints once the API stabilizes.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/dashboard/v2_routes.py`

```python
"""V2 read-only telemetry routes — /runs, /workers, /proxy-state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter


def _runs_dir() -> Path:
    return Path("runs")


def _proxy_state_path() -> Path:
    return Path(".harness") / "proxy_state.json"


def _read_json(p: Path) -> dict[str, Any] | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_runs() -> list[dict[str, Any]]:
    """Return summaries for every run under ./runs."""
    runs: list[dict[str, Any]] = []
    base = _runs_dir()
    if not base.exists():
        return runs
    for run_dir in sorted(base.iterdir()):
        if not run_dir.is_dir():
            continue
        state = _read_json(run_dir / "run_state.json")
        plan = _read_json(run_dir / "plan.json")
        runs.append({
            "run_id": run_dir.name,
            "state": (state or {}).get("state"),
            "tasks": len((plan or {}).get("tasks") or []),
            "started_at": (state or {}).get("started_at"),
            "last_tick_at": (state or {}).get("last_tick_at"),
        })
    return runs


def list_workers(run_id: str) -> list[dict[str, Any]]:
    """Return per-worker summaries for a single run."""
    base = _runs_dir() / run_id / "checkpoints"
    workers: list[dict[str, Any]] = []
    if not base.exists():
        return workers
    for ckpt_path in sorted(base.glob("*.json")):
        data = _read_json(ckpt_path)
        if data is None:
            continue
        workers.append({
            "worker_id": data.get("worker_id"),
            "state": data.get("state"),
            "tests_passed": data.get("tests_passed"),
            "files_modified": data.get("files_modified") or [],
            "commit_sha": data.get("commit_sha"),
            "updated_at": data.get("updated_at"),
        })
    return workers


def proxy_state() -> dict[str, Any]:
    """Return the proxy circuit-breaker + key pool snapshot."""
    return _read_json(_proxy_state_path()) or {"status": "no-state-file"}


def make_router() -> APIRouter:
    router = APIRouter(prefix="/v2")

    @router.get("/runs")
    def _runs() -> list[dict[str, Any]]:
        return list_runs()

    @router.get("/runs/{run_id}/workers")
    def _workers(run_id: str) -> list[dict[str, Any]]:
        return list_workers(run_id)

    @router.get("/proxy-state")
    def _proxy() -> dict[str, Any]:
        return proxy_state()

    return router
```

### 2. Wire into `app.py`

Find `app = FastAPI(...)` in `src/harness/dashboard/app.py` and add
immediately after:

```python
from harness.dashboard.v2_routes import make_router as _v2_make_router
app.include_router(_v2_make_router())
```

### 3. Tests

New file `tests/test_dashboard_v2_routes.py`:

```python
"""Tests for harness.dashboard.v2_routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness.dashboard.v2_routes import list_runs, list_workers, proxy_state, make_router


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_list_runs_returns_empty_when_no_runs_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert list_runs() == []


def test_list_runs_summarises_each_run(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json",
           {"state": "running", "started_at": "2026-05-21T01:00:00Z"})
    _write(tmp_path / "runs" / "r1" / "plan.json",
           {"tasks": [{"worker_id": "worker-1"}, {"worker_id": "worker-2"}]})
    runs = list_runs()
    assert runs == [{
        "run_id": "r1",
        "state": "running",
        "tasks": 2,
        "started_at": "2026-05-21T01:00:00Z",
        "last_tick_at": None,
    }]


def test_list_workers_empty_when_no_checkpoints(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert list_workers("does-not-exist") == []


def test_list_workers_includes_state_and_commit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "checkpoints" / "worker-1.json", {
        "worker_id": "worker-1",
        "state": "completed",
        "tests_passed": True,
        "files_modified": ["a.txt"],
        "commit_sha": "abc1234",
        "updated_at": "2026-05-21T01:00:00Z",
    })
    workers = list_workers("r1")
    assert workers == [{
        "worker_id": "worker-1",
        "state": "completed",
        "tests_passed": True,
        "files_modified": ["a.txt"],
        "commit_sha": "abc1234",
        "updated_at": "2026-05-21T01:00:00Z",
    }]


def test_proxy_state_returns_no_state_file_sentinel(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert proxy_state() == {"status": "no-state-file"}


def test_proxy_state_returns_real_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / ".harness" / "proxy_state.json", {"keys": ["k1", "k2"]})
    assert proxy_state() == {"keys": ["k1", "k2"]}


def test_router_endpoints_are_wired(monkeypatch, tmp_path):
    from fastapi import FastAPI
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json", {"state": "running"})
    _write(tmp_path / "runs" / "r1" / "plan.json", {"tasks": []})
    _write(tmp_path / "runs" / "r1" / "checkpoints" / "worker-1.json",
           {"worker_id": "worker-1", "state": "completed"})

    app = FastAPI()
    app.include_router(make_router())
    client = TestClient(app)

    r = client.get("/v2/runs")
    assert r.status_code == 200
    assert r.json()[0]["run_id"] == "r1"

    r = client.get("/v2/runs/r1/workers")
    assert r.status_code == 200
    assert r.json()[0]["worker_id"] == "worker-1"

    r = client.get("/v2/proxy-state")
    assert r.status_code == 200
```

## Acceptance

- `python -m pytest tests/test_dashboard_v2_routes.py` — all green.
- `python -m pytest --tb=short -q` — overall suite stays green.
- Manual: `harness dashboard-serve` (or test with TestClient) shows
  `/v2/runs`, `/v2/runs/<id>/workers`, `/v2/proxy-state` returning JSON.

## Constraints

- DO NOT touch existing dashboard tests or routes.
- DO NOT add HTML / UI.
- Keep `v2_routes.py` under 120 LOC.
- Use only existing deps (fastapi, stdlib).  Use `fastapi.testclient.TestClient`
  for HTTP-level tests.

## Engine guidance

Single new module + one app.py import + one test file.  swarm/kimi or
swarm/kimi-api works.  Timeout 420s.
