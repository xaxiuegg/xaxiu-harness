"""FastAPI app factory for the operator dashboard.

Surfaces state.json, STATUS.csv, heartbeat, and observer flags via
READ-ONLY REST and WebSocket endpoints.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from harness._constants import _REPO_ROOT
from harness.heartbeat import HEARTBEAT_PATH, read_heartbeat
from harness.observer.flags import list_pending_flags
from harness.state.inspect import DEFAULT_STATE_PATH
from harness.status.store import DEFAULT_STATUS_PATH, read_status, summary as status_summary
from harness.dashboard.v2_routes import make_router as _v2_make_router
from harness.dashboard.v2_routes import list_runs as _list_runs
from harness.dashboard.v2_routes import cost_panel as _cost_panel

_STATIC_DIR: Path = Path(__file__).resolve().parent / "static"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _snapshot() -> dict[str, Any]:
    state = _load_json(DEFAULT_STATE_PATH) or {}
    status_counts = status_summary(DEFAULT_STATUS_PATH)
    heartbeat = read_heartbeat(HEARTBEAT_PATH)
    pending = list_pending_flags()
    flags = []
    for sev in sorted(pending.keys(), key=lambda s: s.value):
        for f in pending[sev]:
            flags.append(f.model_dump(mode="json"))

    wave_plan = state.get("wave_plan") or []
    wave_counts: dict[str, int] = {}
    for w in wave_plan:
        st = str(w.get("status", "?"))
        wave_counts[st] = wave_counts.get(st, 0) + 1

    active_dispatches = state.get("active_dispatches") or []

    runs = _list_runs()
    top_run_workers: list[dict] = []
    if runs:
        from harness.dashboard.v2_routes import list_workers as _list_workers
        top_run_id = max(
            (r for r in runs if r.get("last_tick_at")),
            key=lambda r: r["last_tick_at"],
            default=runs[0],
        )["run_id"]
        top_run_workers = _list_workers(top_run_id)

    snapshot: dict[str, Any] = {
        "type": "snapshot",
        "ts": _now_iso(),
        "state": state,
        "status_summary": {s.value: n for s, n in status_counts.items() if n > 0},
        "wave_plan_counts": wave_counts,
        "heartbeat": heartbeat.model_dump(mode="json") if heartbeat else None,
        "flags": flags,
        "active_dispatches": active_dispatches,
    }
    snapshot["v2"] = {
        "runs": runs,
        "top_run_workers": top_run_workers,
        "cost": _cost_panel(),
    }
    return snapshot


def create_app() -> FastAPI:
    app = FastAPI(title="xaxiu-harness dashboard")
    app.include_router(_v2_make_router())

    # Static assets
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>xaxiu-harness dashboard</h1><p>index.html missing</p>")

    @app.get("/api/state")
    async def api_state() -> dict[str, Any]:
        data = _load_json(DEFAULT_STATE_PATH)
        return data if data is not None else {}

    @app.get("/api/status")
    async def api_status() -> list[dict[str, Any]]:
        rows = read_status(DEFAULT_STATUS_PATH)
        return [r.model_dump(mode="json") for r in rows]

    @app.get("/api/heartbeat")
    async def api_heartbeat() -> dict[str, Any] | None:
        beat = read_heartbeat(HEARTBEAT_PATH)
        return beat.model_dump(mode="json") if beat else None

    @app.get("/api/flags")
    async def api_flags() -> list[dict[str, Any]]:
        pending = list_pending_flags()
        flags: list[dict[str, Any]] = []
        for sev in sorted(pending.keys(), key=lambda s: s.value):
            for f in pending[sev]:
                flags.append(f.model_dump(mode="json"))
        return flags

    @app.get("/api/summary")
    async def api_summary() -> dict[str, Any]:
        state = _load_json(DEFAULT_STATE_PATH) or {}
        status_counts = status_summary(DEFAULT_STATUS_PATH)
        wave_plan = state.get("wave_plan") or []
        wave_counts: dict[str, int] = {}
        for w in wave_plan:
            st = str(w.get("status", "?"))
            wave_counts[st] = wave_counts.get(st, 0) + 1
        active_dispatches = state.get("active_dispatches") or []
        return {
            "status_counts": {s.value: n for s, n in status_counts.items() if n > 0},
            "wave_plan_counts": wave_counts,
            "active_dispatch_count": len(active_dispatches),
        }

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        tick_seconds = float(os.environ.get("HARNESS_DASHBOARD_TICK_SECONDS", "5"))
        try:
            while True:
                payload = _snapshot()
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(payload)
                await asyncio.sleep(tick_seconds)
        except WebSocketDisconnect:
            pass
        except Exception:
            # Swallow send errors on closed sockets
            pass

    return app
