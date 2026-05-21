# Packet: v2/A — Stateful API Proxy + 4-key Routing + Circuit Breaker

## Mission

Implement the stateful API proxy from `spec/multi-agent-harness-architecture.md` §3.4. Unblocks the full 24-slot Kimi pool (4 keys × 6 concurrent) for all future worker dispatches. Single Python process listening on `localhost:7879`, exposing the OpenAI-compatible chat-completion surface that Kimi-API workers will hit.

This is the highest-leverage v2 piece: every future worker call routes through this proxy, so circuit-breaking + load balancing happens for free across the rest of v2.

Disjoint from Wave 6/C (which touches `harness/loops/supervisors.py` only). Both can land in the same window.

## In-scope NEW files

- `src/harness/proxy/__init__.py` — re-exports
- `src/harness/proxy/state.py` — `KeyState` Pydantic model + `ProxyState` aggregate + atomic read/write of `.harness/proxy_state.json`
- `src/harness/proxy/circuit.py` — `CircuitBreaker` per-key state machine (closed/half_open/open) + transition rules
- `src/harness/proxy/router.py` — `pick_key(state) -> KeyAlias | None` (least-loaded, latency-aware)
- `src/harness/proxy/app.py` — FastAPI app exposing `/v1/chat/completions` (OpenAI-compatible); on each inbound request, picks key, increments in_flight, proxies via httpx, classifies outcome, updates state
- `src/harness/proxy/server.py` — `serve(host, port)` runs uvicorn programmatically
- `src/harness/proxy/cli.py` — internal CLI helpers (called from `harness proxy ...` verb group)
- `tests/test_proxy_state.py` — schema + roundtrip + atomic write
- `tests/test_proxy_circuit.py` — state machine transitions
- `tests/test_proxy_router.py` — routing decisions (least_loaded, round_robin)
- `tests/test_proxy_app.py` — FastAPI route tests (TestClient + httpx mock)

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group(name="proxy")` with subcommands: `start`, `stop`, `status`, `reset-circuit`, `quarantine`. ≤50 LOC; logic in `harness.proxy.*`.
- `.gitignore` — append `.harness/proxy_state.json`

## Schemas (src/harness/proxy/state.py)

```python
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class CircuitState(StrEnum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"

class KeyState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    in_flight: int = Field(ge=0, default=0)
    max_concurrent: int = Field(ge=1, le=24, default=6)
    circuit_state: CircuitState = CircuitState.CLOSED
    recent_outcomes: list[str] = Field(default_factory=list, max_length=20)
    consecutive_failures: int = Field(ge=0, default=0)
    cooldown_until: str | None = None
    total_dispatched: int = Field(ge=0, default=0)
    total_failed: int = Field(ge=0, default=0)
    avg_latency_ms: float = Field(ge=0.0, default=0.0)
    last_used_at: str | None = None

class ProxyState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    started_at: str
    keys: dict[str, KeyState] = Field(default_factory=dict)
    routing_strategy: Literal["least_loaded", "round_robin", "random"] = "least_loaded"
    total_requests: int = Field(ge=0, default=0)
    total_errors: int = Field(ge=0, default=0)

def read_state(path: Path) -> ProxyState: ...
def write_state(path: Path, state: ProxyState) -> None: ...  # atomic
```

## Circuit-breaker rules (src/harness/proxy/circuit.py)

State machine, fully tested:

| From | Trigger | To |
|---|---|---|
| closed | consecutive_failures ≥ N (default 3) | open |
| open | cooldown_until <= now | half_open |
| half_open | next request succeeds | closed |
| half_open | next request fails | open (reset cooldown) |

Failure classifications:
- `auth_failure` (HTTP 401/403) → open IMMEDIATELY + `permanent=True` (no auto-recovery)
- `rate_limit` (429) → open with 60s cooldown
- `server_error` (5xx) → open with 30s cooldown
- `timeout` → open with 60s cooldown
- `success` → reset consecutive_failures to 0
- `schema_violation` / `refusal` → does NOT trip breaker (per-request, not per-key)

API:
```python
def classify_outcome(http_status: int | None, exception: Exception | None) -> str: ...
def transition(state: KeyState, outcome: str, *, now: datetime) -> KeyState: ...
def is_routable(state: KeyState, *, now: datetime) -> bool: ...
```

## Routing (src/harness/proxy/router.py)

```python
def pick_key(
    state: ProxyState,
    *,
    now: datetime,
    strategy: str = "least_loaded",
) -> str | None:
    """Pick a routable key.  Returns None if pool saturated/unhealthy."""
    pool = [
        k for k in state.keys.values()
        if circuit.is_routable(k, now=now) and k.in_flight < k.max_concurrent
    ]
    if not pool:
        return None
    if strategy == "least_loaded":
        pool.sort(key=lambda k: (k.in_flight, k.avg_latency_ms))
    elif strategy == "round_robin":
        ...
    elif strategy == "random":
        import random; random.shuffle(pool)
    return pool[0].key_alias
```

## FastAPI app (src/harness/proxy/app.py)

OpenAI-compatible chat completions endpoint. Inbound request shape:
```json
{"model": "kimi-k2", "messages": [...], "temperature": 0.2, ...}
```

For each request:
1. `pick_key()` — if None, return 503 + `{"error": "all_keys_saturated"}` (worker retries after backoff).
2. Increment `in_flight`, persist state (debounced).
3. Forward to actual Moonshot endpoint with `Authorization: Bearer <real_key>`.
4. Capture status code + latency.
5. `transition()` the key state based on outcome.
6. Decrement `in_flight`, persist state.
7. Return upstream response body to caller verbatim (passthrough).

Key storage: read 4 real API keys from env (`KIMI_API_KEY_1` ... `_4`) or DPAPI store (`harness.secrets.dpapi.read_secret("KIMI_API_KEY_1")` etc).

## Operator CLI surface

```python
@cli.group(name="proxy")
def proxy_group() -> None: ...

@proxy_group.command(name="start")
@click.option("--port", default=7879, type=int)
@click.option("--host", default="127.0.0.1")
def proxy_start(port, host): ...

@proxy_group.command(name="stop")
def proxy_stop(): ...   # find PID via .harness/proxy.pid, SIGTERM

@proxy_group.command(name="status")
def proxy_status(): ...   # pretty per-key table: alias | in_flight/max | state | failures | avg_ms

@proxy_group.command(name="reset-circuit")
@click.argument("key_alias")
def proxy_reset(key_alias): ...   # force closed, clear consecutive_failures

@proxy_group.command(name="quarantine")
@click.argument("key_alias")
def proxy_quarantine(key_alias): ...   # force open + permanent=True
```

## Tests required

State (test_proxy_state.py): 6+
- KeyState rejects: blank alias, negative in_flight, invalid CircuitState
- ProxyState roundtrip preserves keys
- Atomic write contract (mock os.replace to raise; original intact)
- Schema-version forward-compat (extra="forbid" rejects unknown fields)

Circuit (test_proxy_circuit.py): 8+
- closed → open after 3 consecutive failures
- open → half_open after cooldown_until passes
- half_open → closed on success
- half_open → open on failure (cooldown reset)
- auth_failure → open immediately + permanent
- success resets consecutive_failures
- schema_violation does NOT trip breaker
- transition preserves total counters

Router (test_proxy_router.py): 5+
- least_loaded picks key with lowest in_flight
- routing skips open keys
- routing skips keys at max_concurrent
- returns None on saturated pool
- round_robin cycles deterministically with stable ordering

App (test_proxy_app.py): 5+
- POST /v1/chat/completions happy path (httpx mock + TestClient)
- 503 when all keys unroutable
- Key in_flight increments then decrements per request
- Auth failure trips circuit immediately
- Successful response is forwarded byte-for-byte

Target ≥24 new tests. Suite ≥546.

## Acceptance criteria

1. `harness proxy start --port 7879` runs the proxy on localhost.
2. `harness proxy status` shows per-key health in <1s.
3. Posting an OpenAI-format request to `localhost:7879/v1/chat/completions` returns a Moonshot response (or 503 if all keys saturated; or upstream error code if Moonshot returned non-2xx).
4. Killing any single key (mocking 3 consecutive 5xx) trips its breaker; subsequent requests route to other keys.
5. `python -m pytest tests/ -q` shows ≥522 + 24 new tests, all green.
6. Single commit: `feat(proxy): stateful 4-key proxy with circuit breaker (v2/A)`.

## Reference

- `spec/multi-agent-harness-architecture.md` §3.4 — full design including state schema, transition rules, routing algorithm
- `src/harness/secrets/dpapi.py::read_secret` — for fetching the 4 real keys
- `src/harness/dashboard/app.py` — pattern for FastAPI app factory + uvicorn serve
- `src/harness/observer/scheduler.py` — pattern for persisted state + atomic write
- Memory `reference_xaxiu_swarm_concurrency_calibration` — 24-slot baseline empirically validated

## Output format

8 new files + 2 modifications + 1 commit. uvicorn binds to 127.0.0.1 only (no external exposure).
