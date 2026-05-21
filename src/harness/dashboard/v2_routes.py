"""V2 read-only telemetry routes — /runs, /workers, /proxy-state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


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
