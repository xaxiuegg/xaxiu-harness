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

    Resolution order (per alias):
      1. ``<env_prefix>_<n>`` env var (e.g. KIMI_API_KEY_1)
      2. DPAPI store under the same name
      3. Legacy singular fallback — if k1 is still missing AND the bare
         ``<env_prefix>`` (no suffix) env var or DPAPI entry is populated,
         use it as k1.  This lets a single-key operator run v2 in
         degraded 6-slot mode without re-storing the key under _1.

    Empty-string values are treated as missing (DPAPI patch 2026-05-21).
    """
    keys: dict[str, str] = {}
    for n in range(1, 5):
        alias = f"k{n}"
        value = os.environ.get(f"{env_prefix}_{n}") or None
        if not value and decrypt_secret is not None:
            try:
                value = decrypt_secret(f"{env_prefix}_{n}")
            except Exception:
                value = None
        if value:
            keys[alias] = value

    # Legacy single-key fallback — populate k1 from bare env_prefix if no
    # indexed keys were resolved.  Operator can rotate to multi-key later.
    if not keys:
        legacy = os.environ.get(env_prefix) or None
        if not legacy and decrypt_secret is not None:
            try:
                legacy = decrypt_secret(env_prefix)
            except Exception:
                legacy = None
        if legacy:
            keys["k1"] = legacy

    return keys


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
        if app_.state.http_client is None:
            app_.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        yield
        # shutdown
        if app_.state.http_client is not None:
            await app_.state.http_client.aclose()

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

    return app
