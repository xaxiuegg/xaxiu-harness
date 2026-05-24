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


def _scan_queue(root: Path | None = None) -> dict[str, Any]:
    """W5-LL 2026-05-23: surface the autonomous orchestrator's spec
    queue (Path β) so the dashboard reflects in-flight + completed
    autonomous work.

    Returns ``{"pending": [...], "done": [...], "pending_count": N,
    "done_count": N}`` with each list containing relative spec names.
    Empty when ``spec/auto/`` doesn't exist (e.g. tests / fresh repo).
    """
    base = (root or _REPO_ROOT) / "spec" / "auto"
    done = base / "done"
    pending: list[str] = []
    completed: list[str] = []
    if base.exists():
        pending = sorted(p.name for p in base.glob("*.md") if p.is_file())
    if done.exists():
        completed = sorted(p.name for p in done.glob("*.md") if p.is_file())
    return {
        "pending": pending,
        "done": completed,
        "pending_count": len(pending),
        "done_count": len(completed),
    }


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
        "queue": _scan_queue(),  # W5-LL: Path β queue visibility
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

    @app.get("/api/queue")
    async def api_queue() -> dict[str, Any]:
        """W5-LL 2026-05-23: expose the autonomous-orchestrator queue
        (Path β / W5-U).  Returns pending + done spec names so operators
        can watch progress without polling git or the filesystem."""
        return _scan_queue()

    # W12-DASHBOARD-WIRE-V2-ROUTES (2026-05-24): the 20-agent operator-
    # review panel found these endpoints returning 404, leaving Wave 11
    # work (cost widget, preflight latency, L5 escalations, loop status)
    # invisible to the dashboard.  Wiring them through to the existing
    # backend modules so the dashboard finally surfaces the Wave 11 work.

    @app.get("/api/loop")
    async def api_loop() -> dict[str, Any]:
        """W12: structured loop status — was previously only in /api/state
        as a nested dict, breaking dashboards that expect a top-level
        loop snapshot."""
        state = _load_json(DEFAULT_STATE_PATH) or {}
        loop = state.get("loop") or {}
        # Add a is_stale + minutes_since_last_tick computation so the
        # dashboard can show the operator how recent the loop actually
        # ran (the May-21 stale-tick problem the panel found).
        from datetime import datetime, timezone
        last_tick = loop.get("last_tick_at") or loop.get("last_tick")
        minutes_since = None
        is_stale = False
        if isinstance(last_tick, str):
            try:
                t = datetime.fromisoformat(last_tick.rstrip("Z"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                minutes_since = int((datetime.now(timezone.utc) - t).total_seconds() / 60)
                is_stale = minutes_since > 60  # >1h since last tick = stale
            except (ValueError, TypeError):
                pass
        return {
            "status": loop.get("status", "unknown"),
            "tick": loop.get("tick", 0),
            "last_tick_at": last_tick,
            "minutes_since_last_tick": minutes_since,
            "is_stale": is_stale,
        }

    @app.get("/api/cost")
    async def api_cost() -> dict[str, Any]:
        """W12: cost-today widget — same data as `harness cost-today`."""
        try:
            from harness.cost_widget import cost_widget_dict
            return cost_widget_dict(since_hours=24.0)
        except Exception as exc:
            return {"error": str(exc), "spent_usd": 0.0,
                    "budget_usd": 5.0, "status": "error"}

    @app.get("/api/preflight-latency")
    async def api_preflight_latency() -> dict[str, Any]:
        """W12: rolling p50/p95 of preflight checks — same data as
        `harness preflight-latency --format json`."""
        try:
            from harness.preflight_latency import latency_summary
            return latency_summary(since_hours=24.0)
        except Exception as exc:
            return {"error": str(exc), "count": 0,
                    "p50": 0, "p95": 0, "p99": 0, "per_check": {}}

    @app.get("/api/l5-events")
    async def api_l5_events() -> dict[str, Any]:
        """W12: L5 escalations in last 24h — surfaces:
        - CRITICAL observer flags in coord/observer/flags/
        - Watchdog consecutive_restart_failures >= 3
        Same signal `harness today` shows in its L5 section."""
        events: list[dict[str, Any]] = []
        # CRITICAL observer flags
        try:
            from harness._constants import _REPO_ROOT
            crit = _REPO_ROOT / "coord" / "observer" / "flags" / (
                "CRITICAL_FLAG_PENDING.md"
            )
            if crit.exists():
                from datetime import datetime, timezone
                mtime = datetime.fromtimestamp(
                    crit.stat().st_mtime, tz=timezone.utc,
                )
                events.append({
                    "source": "observer_critical_flag",
                    "raised_at": mtime.isoformat(),
                    "code": "L5.observer.CRITICAL_FLAG",
                    "summary": "CRITICAL observer flag pending",
                    "action": "run `harness observer flags` for detail",
                })
        except Exception:
            pass
        # Watchdog escalation
        try:
            from harness.observer import state as _ostate
            from harness import l5_escalation as _l5
            st = _ostate.read_state()
            if _l5.should_escalate_to_l5(st.consecutive_restart_failures):
                events.append({
                    "source": "watchdog_consecutive_failures",
                    "code": "L5.observer.OBSERVER_RESTART_LOOP",
                    "summary": (f"observer restart failed "
                                f"{st.consecutive_restart_failures} "
                                f"consecutive times"),
                    "action": (
                        "run `harness observer restart` (will print "
                        "full L5 banner)"
                    ),
                    "consecutive_failures": st.consecutive_restart_failures,
                })
        except Exception:
            pass
        return {"count": len(events), "events": events}

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
