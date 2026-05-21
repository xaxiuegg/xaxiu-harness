# Packet: Wave 3 — Dashboard backend + frontend (FastAPI + WebSocket)

## Mission

Implement the operator-facing real-time dashboard per the harness roadmap. Surfaces every primitive shipped this session (STATUS.csv, state.json, observer flags, heartbeat) on a single web page that auto-updates via WebSocket. Operator can open it once and watch the loop work without scrolling chat history.

All upstream primitives are now in place:
- `src/harness/status/` — STATUS.csv reader/writer (read_status, summary, verify)
- `src/harness/state/inspect.py` — render_state_json + summary helpers
- `src/harness/heartbeat.py` — pulse/read_heartbeat/format_for_human
- `src/harness/observer/flags.py` — list_pending_flags

## In-scope NEW files

- `src/harness/dashboard/__init__.py` — re-exports
- `src/harness/dashboard/app.py` — FastAPI app factory `create_app()` with REST + WebSocket routes
- `src/harness/dashboard/server.py` — `serve(host, port)` runs uvicorn programmatically
- `src/harness/dashboard/static/index.html` — single-page UI (vanilla JS, no framework)
- `src/harness/dashboard/static/style.css` — minimal CSS (operator-readable, no design system needed)
- `src/harness/dashboard/static/script.js` — WebSocket client + DOM updater
- `tests/test_dashboard.py` — REST route tests + WebSocket smoke + render correctness

## In-scope MODIFY files

- `src/harness/cli.py` — wire the existing `dashboard-serve` command (currently a stub) to `harness.dashboard.server.serve(host, port)`. Keep cli.py footprint minimal: ≤15 LOC.

## REST routes

```python
# src/harness/dashboard/app.py

@app.get("/")               # → returns static/index.html (or templated)
@app.get("/api/state")      # → JSON dump of coord/dev_loop/state.json
@app.get("/api/status")     # → JSON list of StatusRow dicts
@app.get("/api/heartbeat")  # → JSON of latest heartbeat (or null)
@app.get("/api/flags")      # → JSON list of pending observer flags
@app.get("/api/summary")    # → aggregated counts: status counts + wave_plan counts + active dispatch count
@app.websocket("/ws")       # → pushes the same payloads on a 5s cadence
```

All routes are READ-ONLY. No mutation through the dashboard.

## WebSocket payload contract

```json
{
  "type": "snapshot",
  "ts": "2026-05-21T01:50:00Z",
  "state": { /* state.json summary */ },
  "status_summary": {"shipped": 34, "planned": 2, ...},
  "heartbeat": { /* harness.heartbeat.Heartbeat */ },
  "flags": [ /* list of pending Flag dicts */ ],
  "active_dispatches": [ /* state.active_dispatches */ ]
}
```

Push every 5s (configurable via env `HARNESS_DASHBOARD_TICK_SECONDS`, default 5).

## Frontend (vanilla JS)

```html
<!-- src/harness/dashboard/static/index.html -->
<!DOCTYPE html>
<html>
<head>
  <title>xaxiu-harness dashboard</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <h1>xaxiu-harness</h1>
  <section id="loop"></section>
  <section id="phases"></section>
  <section id="dispatches"></section>
  <section id="status-summary"></section>
  <section id="wave-plan"></section>
  <section id="flags"></section>
  <footer id="heartbeat"></footer>
  <script src="/static/script.js"></script>
</body>
</html>
```

`script.js` opens a WebSocket to `/ws`, parses each snapshot, and updates the sections in-place. No build step, no framework.

## CLI wiring (src/harness/cli.py)

Replace the existing stub:

```python
@cli.command(name="dashboard-serve")
@click.option("--port", default=7878, type=int)
@click.option("--host", default="127.0.0.1")
def dashboard_serve(port: int, host: str) -> None:
    """Run the operator-facing dashboard."""
    from harness.dashboard.server import serve
    serve(host=host, port=port)
```

## Tests required

1. `create_app()` returns a FastAPI app with the expected routes.
2. GET `/api/state` returns valid JSON matching state.json content (use TestClient).
3. GET `/api/status` returns array of StatusRow dicts.
4. GET `/api/heartbeat` returns null when no heartbeat exists; valid dict after pulse.
5. GET `/api/flags` returns empty list when no flags pending; populated list when flags exist (mock observer state).
6. GET `/api/summary` aggregates correctly.
7. WebSocket `/ws` sends a snapshot within 6 seconds of connection (use websockets test client).
8. Frontend smoke: `static/index.html` exists + references `/static/script.js` and `/static/style.css`.
9. `harness dashboard-serve --port 7879` smoke (don't actually bind — assert the cli invocation calls `serve`).

Use `pytest-asyncio` for WebSocket tests (already in dev deps).

## Acceptance criteria

1. `harness dashboard-serve --port 7878` starts uvicorn and serves the dashboard.
2. Visiting `http://localhost:7878/` shows live state.
3. The page updates within 5s when STATUS.csv or state.json changes (verified by smoke: pulse heartbeat → next WebSocket frame contains updated tick_count).
4. All 5 REST endpoints return valid JSON.
5. `python -m pytest tests/ -q` shows ≥399 + new tests, all green.
6. Single commit: `feat(dashboard): FastAPI + WebSocket operator dashboard (Wave 3)`.

## Reference

- `src/harness/status/`, `src/harness/state/inspect.py`, `src/harness/heartbeat.py`, `src/harness/observer/flags.py` — upstream primitives this dashboard composes
- `pyproject.toml` declares `fastapi>=0.110`, `uvicorn[standard]>=0.27`, `websockets>=12.0`, `httpx>=0.27` — all already installed in this venv
- Memory `user_non_technical_role` — output style must be operator-readable, not engineer-formatted

## Output format

7 new files + 1 cli.py modification + 1 commit. Vanilla JS frontend (no build step). uvicorn binds to 127.0.0.1 by default (no external exposure).
