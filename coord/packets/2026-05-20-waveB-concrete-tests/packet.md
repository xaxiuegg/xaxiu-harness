# Packet: Wave B/1 — boundary tests for engines/concrete.py

## Mission

Add boundary tests for `src/harness/engines/concrete.py` covering all three engine HTTP clients (DeepseekConcrete, KimiConcrete, AnthropicConcrete). Push coverage of that module from current 20% to >60%.

## Scope (disjoint from Wave B/2)

In-scope NEW file: `tests/test_engines_concrete_boundary.py` only.

Out-of-scope:
- `tests/test_engines_guards_boundary.py` (sibling packet, Wave B/2)
- Any modification to `src/harness/engines/concrete.py` itself
- Any existing test files

## Required tests (per-engine, mock httpx via `httpx.MockTransport`)

For each of `DeepseekConcrete`, `KimiConcrete`, `AnthropicConcrete`:

1. **Success path** — mock returns 200 with valid JSON. Verify URL, headers, auth, body shape; assert `EngineResponse.success is True` and `text` matches.
2. **HTTP 401** — mock returns 401. Assert `success=False`, `error` mentions auth.
3. **HTTP 429** — mock returns 429 with Retry-After. Assert `success=False`, `retry_eligible` (or equivalent) is True.
4. **HTTP 5xx** — mock returns 500. Assert `success=False`.
5. **Network error** — mock raises `httpx.ConnectError`. Assert `success=False`, not propagated.
6. **Timeout** — mock raises `httpx.TimeoutException`. Assert `success=False`.
7. **Malformed JSON** — mock returns 200 with non-JSON body. Assert `success=False`, not an unhandled exception.

## Pattern

Use `httpx.MockTransport` (stdlib of httpx, no new dep):

```python
import httpx, pytest
from harness.engines.concrete import KimiConcrete  # adapt per test

def _mock_response(status_code=200, json_body=None, exc=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if exc:
            raise exc
        return httpx.Response(status_code, json=json_body or {})
    return httpx.MockTransport(handler)

# Inject mock into engine's client somehow (read the constructor — likely accepts a client or has a factory)
```

If the engine class doesn't currently accept a transport for injection, write the test to monkeypatch `httpx.Client` or `httpx.AsyncClient` via `monkeypatch.setattr`. Do NOT modify `concrete.py`.

## Acceptance criteria

1. `python -m pytest tests/ -q` shows ≥89 + new tests, all green.
2. `python -m pytest tests/ --cov=src/harness/engines/concrete --cov-report=term-missing | tail -10` shows `engines/concrete.py` coverage > 60%.
3. No modifications to any file outside `tests/test_engines_concrete_boundary.py`.
4. Single commit at the end: `test(engines/concrete): boundary tests (Wave B/1)`.

## Reference

- `src/harness/engines/concrete.py` — what's being tested (read it first)
- `src/harness/engines/base.py` — `EngineResponse` dataclass shape
- `tests/test_dispatcher.py` — patterns for mocking and async tests if needed
- httpx docs: https://www.python-httpx.org/advanced/transports/#mock-transports

## Output format

Single new file at `tests/test_engines_concrete_boundary.py`. No modifications elsewhere.
