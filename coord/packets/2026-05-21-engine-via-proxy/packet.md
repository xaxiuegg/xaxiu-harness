# Packet: engines/concrete.py routes through the v2 proxy

## Mission

v2 production-readiness audit gap #4: `KimiConcrete.dispatch` posts directly to `https://api.moonshot.cn/v1/chat/completions`. The 4-key proxy at `localhost:7879` is dark — exists but never receives traffic. Make Kimi-API engines route through the proxy by default; allow explicit upstream override for testing.

Disjoint from coord-wiring (different package) and mock-engine (new file).

## In-scope MODIFY files

- `src/harness/engines/concrete.py` — KimiConcrete (and KimiApiConcrete if separate) default `upstream_url` to `http://127.0.0.1:7879/v1/chat/completions` when env `HARNESS_PROXY_URL` is set OR when a proxy PID file exists at `.harness/proxy.pid`; otherwise fall back to direct Moonshot endpoint
- `src/harness/proxy/app.py` — add `/healthz` route returning `{"status": "ok", "pool_size": <int>, "in_flight": <int>}` (used by coord-run preflight)
- `tests/test_engines_concrete_boundary.py` — extend with proxy-routing tests (mocked httpx)

## In-scope NEW files

NONE.

## Required behavior

### concrete.py default URL resolution

```python
def _resolve_kimi_upstream() -> str:
    """Route through local proxy when available, else direct."""
    # Operator-set override
    explicit = os.environ.get("HARNESS_PROXY_URL")
    if explicit:
        return explicit
    # Proxy running?
    pid_file = Path(".harness") / "proxy.pid"
    if pid_file.exists():
        return "http://127.0.0.1:7879/v1/chat/completions"
    # Fall back to direct
    return "https://api.moonshot.cn/v1/chat/completions"
```

KimiConcrete + KimiApiConcrete both call this. Kimi-CLI subprocess path (xaxiu-swarm) is unchanged — that's a separate binary.

### proxy /healthz

```python
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
```

### `harness proxy start` writes PID file

(If not already — add `.harness/proxy.pid` write on server startup, remove on shutdown.) Lets concrete.py detect proxy presence.

## Tests required

1. `_resolve_kimi_upstream` with `HARNESS_PROXY_URL=http://x` returns x
2. `_resolve_kimi_upstream` with proxy PID file present returns localhost:7879
3. `_resolve_kimi_upstream` with no env + no PID returns direct Moonshot URL
4. KimiConcrete.dispatch with proxy URL routes correctly (mocked httpx)
5. `/healthz` endpoint returns expected dict shape (TestClient)
6. `/healthz` survives empty key pool (pool_size=0)

Target ≥5 new tests.

## Acceptance criteria

1. `harness proxy start` writes `.harness/proxy.pid`; `harness proxy stop` removes it.
2. Running KimiConcrete with proxy up routes traffic through localhost:7879 (verified by httpx mock).
3. `harness proxy status` queries `/healthz`.
4. `pytest tests/ -q` green.
5. Single commit: `feat(engines): KimiConcrete routes through localhost proxy when available`.

## Reference

- src/harness/engines/concrete.py::KimiConcrete (existing direct-to-Moonshot)
- src/harness/proxy/app.py (the proxy that's currently dark)
- spec/multi-agent-harness-architecture.md §3.4

## Output format

2 file modifications + 1 test extension + 1 commit.
