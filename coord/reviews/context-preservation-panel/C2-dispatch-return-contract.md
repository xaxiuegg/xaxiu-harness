<!-- persona=C2-dispatch-return-contract status=OK (35586ms) -->

# C2-dispatch-return-contract

## 1. Headline recommendation

Ship `dispatch()` with default `return_mode='ref'` so each call adds ≤80 tokens to agent context regardless of response size.

## 2. Concrete API signature and data shape

```python
from typing import Literal, Optional

@dataclass
class DispatchResult:
    success: bool                       # always present
    engine_used: str                    # e.g., "swarm/kimi"
    dispatch_id: str                    # UUID for later retrieval
    fallback_chain: list[str]           # engines tried
    tokens_used: int
    cost_usd: float
    # The following fields are mode-dependent:
    text: Optional[str] = None          # full text, only present in 'full' mode
    summary: Optional[str] = None       # ~200‑char summary, only present in 'summary' mode

    def fetch_text(self) -> str:
        """Retrieve full response from harness store (async or sync).
        Raises if response no longer available."""
        ...

    def fetch_summary(self) -> str:
        """Retrieve AI‑generated summary from harness store."""
        ...

def dispatch(
    prompt: str,
    engine: str | list[str] | None = None,
    *,
    return_mode: Literal["ref", "summary", "full"] = "ref",
    **kwargs
) -> DispatchResult:
    """
    Send prompt to harness engines.  The default 'ref' mode returns only
    metadata (dispatch_id, tokens_used, cost).  No text or summary is loaded
    into the agent’s context.  Use .fetch_text() or .fetch_summary() on the
    returned object to retrieve the content when needed – this places the
    result string under the agent’s explicit control.

    Modes:
      'ref'      – text=None, summary=None.
      'summary'  – summary is populated (~200 chars), text=None.
      'full'     – text is populated (legacy behaviour).
    """
```

## 3. Default that maximises context preservation

**`return_mode='ref'`** – the returned `DispatchResult` is ~80 bytes (success, engine, dispatch_id, tokens, cost). The agent can build logic to decide later whether to read the full output. For 30 dispatches, the agent context grows by ~2 400 tokens vs. ~750 000 tokens if `full` were used (assuming 25 K per response). This is the maximum offload: the agent never touches the response text unless it explicitly invokes `fetch_text()`.

## 4. Escape hatch when the agent needs the full response

- **Immediate full text**: call `dispatch(..., return_mode='full')` – returns `DispatchResult` with `.text` populated (same as current API).
- **Deferred access**: use the default `ref` mode, then later call `result.fetch_text()` or `result.fetch_summary()`. The agent can read the returned string into a variable (and thus into context) only when it decides the response is critical.
- **Summarised on-demand**: `result.fetch_summary()` returns a short (≤200 char) AI‑condensed version, which the agent may put into context with minimal token cost.

## 5. One risk specific to this lens

**Retrieval latency / availability** – the harness must retain dispatches (text + summary) long enough for the agent to call `fetch_text()`. If the agent runs in a long session and may fetch old results hours later, the store must be persistent across time. If the store drops entries (e.g., after 10 minutes), calls to `fetch_text()` will fail, and the agent may be forced to re‑dispatch, wasting tokens. The design must guarantee that all dispatch results are kept for at least the session’s lifetime (or until explicitly purged by the agent). This requires a durability contract between the harness and the store (Redis / S3 with TTL tied to session ID).
