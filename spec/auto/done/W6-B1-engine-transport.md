# W6-B1 — Extract `StreamingTransport` base class for SSE engines

## Planner guidance

**Single-worker preferred.** The new module + 3 engine retrofits + 1 test file are tightly coupled. Splitting across workers risks contract drift (the same issue queued as W7-SPEC-DRIFT in STATUS.csv).

A single worker with `write_set: ["src/harness/engines/transport.py", "src/harness/engines/concrete.py", "tests/test_engines_transport.py"]` is the correct shape.

## Context

`src/harness/engines/concrete.py` ships three classes — `DeepSeekConcrete`, `KimiConcrete`, `MiMoConcrete` — each of which independently re-implements a near-identical streaming HTTP loop:

1. Open an `httpx.Client(...)` with `stream("POST", url, headers, json=payload)`
2. Iterate `r.iter_lines()`
3. For each line, strip `"data: "` or `"data:"` prefix
4. Break on `[DONE]`
5. JSON-decode chunk, pull `choices[0].delta.content`, append to a list
6. Capture `usage.prompt_tokens` / `usage.completion_tokens` from the final chunk
7. Track `finish_reason`
8. Return `EngineResponse(text="".join(chunks), tokens_in=..., tokens_out=...)` on success, or `EngineResponse(success=False, error="parse_error_no_chunks")` if literally nothing was parsed

The duplication is ~80 lines per engine × 3 engines = ~240 lines of structurally identical code. Every SSE bug (W5-V Kimi 0/10, W5-MM DeepSeek streaming, MiMo data:-no-space variant) had to be fixed three times.

## Goal

Create `src/harness/engines/transport.py` containing a `StreamingTransport` ABC that owns the streaming loop ONCE. Each concrete engine declares only:

- `endpoint_url() -> str`
- `headers() -> dict[str, str]`
- `build_payload(packet: str, model: str, extra: dict) -> dict`

The base class provides a concrete `dispatch(packet, model, extra) -> EngineResponse` that runs the shared streaming loop, handles all SSE variations, and produces a properly-typed `EngineResponse`.

## Required structure

```python
# src/harness/engines/transport.py
from abc import abstractmethod
import httpx, json, time
from harness.engines.base import Engine, EngineResponse

class StreamingTransport(Engine):
    """Engine subclass that owns the OpenAI-compat SSE streaming loop.

    Subclasses provide endpoint, headers, and payload — the base owns
    the streaming, prefix handling, [DONE] terminator, content
    aggregation, usage extraction, and error mapping.
    """

    @abstractmethod
    def endpoint_url(self) -> str: ...

    @abstractmethod
    def headers(self) -> dict[str, str]: ...

    @abstractmethod
    def build_payload(self, packet: str, model: str, extra: dict) -> dict: ...

    def dispatch(self, packet, model, extra_args=None) -> EngineResponse:
        # ... shared streaming loop ...
```

The shared loop must:
- Use `httpx.Client(verify=True, timeout=_DEFAULT_TIMEOUT).stream(...)`
- Handle BOTH `"data: "` and `"data:"` prefixes (W5-V wiring fix)
- Break on `[DONE]` line
- JSON-decode each chunk; skip on decode error
- Append `choices[0].delta.content` to a list
- Capture `usage.prompt_tokens` / `usage.completion_tokens`
- Return `success=False, error="parse_error_no_chunks"` when nothing was parsed
- Return `success=True, text=...` joined chunks otherwise
- Catch `httpx.TimeoutException`, `httpx.HTTPStatusError`, `httpx.ConnectError` and map to `EngineResponse(success=False, error=...)`

## Retrofit

Refactor `DeepSeekConcrete`, `KimiConcrete`, `MiMoConcrete` to inherit from `StreamingTransport`. After the refactor:

- Each engine class should be ≤50 LOC (most of the bulk moves to the base)
- The 3 engines' `dispatch()` methods should be REMOVED — replaced by the base class implementation
- The engine-specific differences (deepseek's `--no-thinking`, mimo's `auto` model routing, kimi's reasoning_content channel) stay in the subclass's `build_payload` or in a small overrideable hook

**Important**: Kimi's reasoning_content channel (lines 410-411 in current concrete.py) is captured separately. If retrofitting Kimi via the base class, expose an overrideable hook (e.g. `_extract_chunk_extra(delta)`) so subclasses can capture engine-specific fields. Don't drop the reasoning_content path silently.

## Acceptance

- `pytest tests/ -q` stays green (all 1426 + 4 skipped must still pass)
- Existing engine tests in `tests/test_engines_concrete.py` continue to pass — the retrofit must be behavior-preserving
- ≥80 lines of duplicated SSE parsing now live in ONE place (`transport.py`)
- A new test file `tests/test_engines_transport.py` covers:
  - The base class's SSE loop with a mocked `httpx.Client`
  - Both `data: ` and `data:` prefixes
  - `[DONE]` terminator
  - `parse_error_no_chunks` path (empty stream)
  - Timeout → `success=False, error="timeout"`
  - HTTP 500 → `success=False, error="HTTP 500"`
- Each refactored engine class ≤80 LOC (down from ~150-200 today)

## File scope

- `src/harness/engines/transport.py` — new ~150 LOC base class
- `src/harness/engines/concrete.py` — remove duplicated dispatch loops from DeepSeekConcrete, KimiConcrete, MiMoConcrete (net negative LOC)
- `tests/test_engines_transport.py` — new ~120 LOC test file

## Why this spec exists

W6-B1: Architect reviewer flagged the SSE parsing as the #1 source of bug-class duplication. The W5-V Kimi 0/10 → 3/3 fix had to be re-applied per engine; consolidating eliminates that bug-class.

## Output format reminder

The worker prompt includes the existing contents of `src/harness/engines/concrete.py` (W6-A1-3 fix). Emit FILE/REPLACE blocks. For `transport.py` and `test_engines_transport.py`, use empty SEARCH (create-new-file idiom). For `concrete.py`, anchor SEARCH blocks on the existing `class DeepSeekConcrete:` / `class KimiConcrete:` / `class MiMoConcrete:` lines and replace through to the end of each `dispatch()` method.

Both files modified by ONE worker. Stdlib + httpx + existing harness internals only.
