"""FastAPI proxy application for Kimi API."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from harness.proxy.circuit import classify_outcome, transition
from harness.proxy.router import pick_key
from harness.proxy.state import KeyState, ProxyState, read_state, write_state

try:
    from harness.secrets.dpapi import decrypt_secret
except NotImplementedError:  # pragma: no cover
    decrypt_secret = None

DEFAULT_UPSTREAM = "https://api.moonshot.cn/v1/chat/completions"


def _state_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return Path(".harness") / "proxy_state.json"


def resolve_keys(env_prefix: str = "KIMI_API_KEY") -> dict[str, str]:
    """Discover API keys from environment and DPAPI fallback.

    Delegates to ``harness.keys.resolve_keys`` (W14-KEYS-POOL
    2026-05-26) so the resolution logic is shared with the Pattern B
    engines and the keys UI.  Returns the same ``{alias: value}`` dict
    shape as before for backward compatibility with proxy callers.

    Resolution order (per alias):
      1. ``<env_prefix>_<n>`` env var (e.g. KIMI_API_KEY_1)
      2. DPAPI store under the same name
      3. Legacy singular fallback — if no indexed keys AND the bare
         ``<env_prefix>`` is populated, use it as k1.

    Empty-string values are treated as missing.
    """
    from harness.keys import resolve_keys as _generic
    return _generic(env_prefix)


def _init_state(keys: dict[str, str]) -> ProxyState:
    now = datetime.now(timezone.utc).isoformat()
    key_states = {
        alias: KeyState(key_alias=alias, max_concurrent=6)
        for alias in keys
    }
    return ProxyState(started_at=now, keys=key_states)


def create_app(
    state_path: Path | None = None,
    upstream_url: str | None = None,
    keys: dict[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        # startup
        path: Path = app_.state.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            state = _init_state(app_.state.keys)
            write_state(state, path)
        pid_path = path.parent / "proxy.pid"
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        if app_.state.http_client is None:
            app_.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        yield
        # shutdown
        if app_.state.http_client is not None:
            await app_.state.http_client.aclose()
        try:
            pid_path.unlink()
        except OSError:
            pass

    app = FastAPI(title="xaxiu-harness proxy", lifespan=lifespan)
    app.state.state_path = _state_path(state_path)
    app.state.upstream_url = upstream_url or DEFAULT_UPSTREAM
    app.state.keys = keys if keys is not None else resolve_keys()
    app.state.http_client = http_client
    app.state.lock = asyncio.Lock()

    async def _load_or_init_state() -> ProxyState:
        path: Path = app.state.state_path
        if path.exists():
            return read_state(path)
        state = _init_state(app.state.keys)
        write_state(state, path)
        return state

    @app.post("/v1/chat/completions")
    async def _proxy(request: Request) -> Response:
        async with app.state.lock:
            state = await _load_or_init_state()
            now = datetime.now(timezone.utc)
            alias = pick_key(state, now=now)
            if alias is None:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "No routable keys available."},
                )
            state.keys[alias].in_flight += 1
            state.total_requests += 1
            write_state(state, app.state.state_path)

        key = app.state.keys[alias]
        body = await request.body()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        client: httpx.AsyncClient = app.state.http_client
        exc: Exception | None = None
        status_code: int | None = None
        response_body = b""
        try:
            resp = await client.post(
                app.state.upstream_url,
                headers=headers,
                content=body,
            )
            status_code = resp.status_code
            response_body = resp.content
        except Exception as e:  # pragma: no cover
            exc = e

        async with app.state.lock:
            state = await _load_or_init_state()
            state.keys[alias].in_flight -= 1
            outcome = classify_outcome(status_code, exc)
            transition(state.keys[alias], outcome, now=datetime.now(timezone.utc))
            if outcome != "success":
                state.total_errors += 1
            write_state(state, app.state.state_path)

        return Response(content=response_body, status_code=status_code or 502)

    @app.get("/healthz")
    async def _healthz():
        state = await _load_or_init_state()
        in_flight_total = sum(k.in_flight for k in state.keys.values())
        return {
            "status": "ok",
            "pool_size": len(state.keys),
            "in_flight": in_flight_total,
            "max_concurrent": sum(k.max_concurrent for k in state.keys.values()),
        }

    return app
