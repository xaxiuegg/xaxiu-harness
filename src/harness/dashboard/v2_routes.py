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
