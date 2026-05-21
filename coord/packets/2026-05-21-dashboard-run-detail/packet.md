# DASHBOARD-RUN-DETAIL-PAGE — `/runs/<id>` HTML view

## Goal

The dashboard exposes `/v2/runs` + `/v2/runs/<id>/workers` JSON endpoints
but no HTML view.  Operators have to GET those endpoints by hand or read
the JSON in the WS stream.  This wave adds a single-page HTML route at
`/runs/<run_id>` that renders a small worker grid + checkpoint summary
using the existing JSON helpers — no JavaScript framework, just plain
HTML + a tiny vanilla-JS fetcher.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/dashboard/v2_routes.py`

Add a NEW HTML route to the existing `make_router()` function (do not
modify the existing /v2/* JSON routes):

```python
from fastapi.responses import HTMLResponse

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

    @router.get("/runs/{run_id}", response_class=HTMLResponse)
    def _run_detail(run_id: str) -> str:
        return _render_run_detail_html(run_id)

    return router


def _render_run_detail_html(run_id: str) -> str:
    """Render a self-contained HTML page for one run."""
    workers = list_workers(run_id)
    runs = {r["run_id"]: r for r in list_runs()}
    meta = runs.get(run_id, {"state": "unknown", "tasks": 0})

    rows: list[str] = []
    for w in workers:
        wid = (w.get("worker_id") or "-")
        state = (w.get("state") or "-")
        files = ", ".join(w.get("files_modified") or []) or "—"
        sha = w.get("commit_sha") or "—"
        tests = "✓" if w.get("tests_passed") else "—"
        rows.append(
            f"<tr><td>{wid}</td><td>{state}</td><td>{tests}</td>"
            f"<td><code>{sha}</code></td><td><small>{files}</small></td></tr>"
        )
    rows_html = "\n".join(rows) if rows else "<tr><td colspan='5'>no workers</td></tr>"

    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>run {run_id}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 2em auto; padding: 0 1em; }}
h1 {{ font-size: 1.4em; }}
.meta {{ color: #666; margin-bottom: 1em; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #eee; padding: 6px 10px; text-align: left; }}
th {{ background: #f7f7f7; }}
code {{ background: #f4f4f4; padding: 1px 4px; }}
.state-completed {{ color: #060; }}
.state-failed {{ color: #b00; }}
.state-running {{ color: #04a; }}
</style>
</head><body>
<h1>run <code>{run_id}</code></h1>
<div class="meta">state: <strong class="state-{meta.get('state','unknown')}">{meta.get('state','unknown')}</strong> · tasks: {meta.get('tasks', 0)} · started: {meta.get('started_at') or '-'}</div>
<table>
<thead><tr><th>worker</th><th>state</th><th>tests</th><th>commit</th><th>files</th></tr></thead>
<tbody>
{rows_html}
</tbody></table>
<p><a href="/v2/runs/{run_id}/workers">raw JSON</a> · <a href="/v2/runs">all runs</a></p>
</body></html>"""
```

### 2. Tests

`tests/test_dashboard_run_detail.py`:

```python
"""Tests for dashboard /v2/runs/<id> HTML view."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.dashboard.v2_routes import make_router


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(make_router())
    return app


def test_run_detail_returns_html(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json", {
        "state": "running", "started_at": "2026-05-21T01:00:00Z",
    })
    _write(tmp_path / "runs" / "r1" / "plan.json", {"tasks": [{"worker_id": "w1"}]})
    client = TestClient(_make_app())
    r = client.get("/v2/runs/r1")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "run <code>r1</code>" in r.text
    assert "state: <strong" in r.text


def test_run_detail_includes_workers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json", {"state": "completed"})
    _write(tmp_path / "runs" / "r1" / "plan.json", {"tasks": []})
    _write(tmp_path / "runs" / "r1" / "checkpoints" / "worker-1.json", {
        "worker_id": "worker-1", "state": "completed",
        "tests_passed": True, "files_modified": ["a.txt", "b.txt"],
        "commit_sha": "abc1234",
    })
    client = TestClient(_make_app())
    r = client.get("/v2/runs/r1")
    assert r.status_code == 200
    assert "worker-1" in r.text
    assert "abc1234" in r.text
    assert "a.txt" in r.text


def test_run_detail_unknown_run_renders_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(_make_app())
    r = client.get("/v2/runs/does-not-exist")
    assert r.status_code == 200
    assert "no workers" in r.text
    assert "state: <strong class=\"state-unknown\">unknown" in r.text
```

## Acceptance

- `python -m pytest tests/test_dashboard_run_detail.py` — green.
- Full suite stays green.
- Manual: `harness dashboard-serve` then `curl http://127.0.0.1:7878/v2/runs/<id>`
  returns HTML.

## Constraints

- DO NOT touch JSON routes or list_runs/list_workers/proxy_state helpers.
- DO NOT add JavaScript frameworks; vanilla HTML + inline CSS only.
- Keep _render_run_detail_html under 80 LOC.
- Stdlib + fastapi only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
