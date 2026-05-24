<!-- persona=C4-cost-aware-routing status=OK (19353ms) -->

# C4-cost-aware-routing

## COST-AWARE ROUTING + TELEMETRY

### 1. Headline recommendation

Make `dispatch()` return a lightweight `DispatchReceipt` by default, and expose real-time per-session telemetry via `budget_status()` so the agent can monitor offload ratio and enforce a hard budget ceiling.

### 2. Concrete numbers / API signature / data shape

```python
# Default dispatch – returns minimal receipt (no full text)
from harness import dispatch, budget_status

receipt: DispatchReceipt = dispatch(
    prompt="summarize …",
    return_full=False,          # default
    engine="auto",              # cheapest-first router
    budget_usd=0.20,            # optional per-call cap
    max_latency=10.0            # seconds, fallback if cheapest too slow
)

# DispatchReceipt fields
class DispatchReceipt(NamedTuple):
    dispatch_id: str            # "abc-123"
    engine: str                 # "deepseek-v4-flash"
    tokens_in: int              # 20_000
    tokens_out: int             # 22_000
    cost_usd: float             # 0.0003
    latency_ms: float           # 1200
    # no .text, no error, no fallback chain

# Retrieving full text only when needed (escape hatch)
full_result: DispatchResult = dispatch(
    prompt="summarize …",
    return_full=True,           # opt‑in to full text in context
)

# Or later, from a receipt:
from harness import get_dispatch_text
text: str = get_dispatch_text(receipt.dispatch_id)  # burns context

# Budget & offload telemetry
status: dict = budget_status()
# {
#     "session_tokens_total": 1500000,
#     "session_cost_total": 0.14,
#     "offload_ratio": 0.85,            # harness / total tokens
#     "remaining_budget_usd": 5.00,     # user‑set ceiling
#     "dispatches_fired": 18,
#     "engines_used": {
#         "deepseek-v4-flash": 12,
#         "kimi": 5,
#         "mimo": 1
#     },
#     "avg_cost_per_token": 9.3e-8
# }
```

### 3. The default that maximizes context preservation

**`return_full=False`** and **`engine="auto"`** (cheapest-first routing).  
The receipt is ~200 bytes per dispatch – negligible compared to full text (5–50 KB). Over 30 dispatches, context growth from receipts ≈ 6 KB vs 750 KB+ for full responses.

The cheapest-first router uses a cost-per-token table (updated every dispatch) and current `budget_status()["remaining_budget_usd"]` to select the engine with lowest marginal cost that meets latency tolerances. If budget is exhausted, it falls back to the free engine (MiMo) or halts.

### 4. The escape hatch

Two explicit opt‑ins to get full text without paying the context tax for the common case:

- **Per-dispatch**: pass `return_full=True` in the call.  
  The agent consciously decides to ingest the response immediately.

- **Deferred retrieval**: call `harness.get_dispatch_text(id)` after the fact.  
  This allows the agent to decide *after* reviewing the receipt whether the response is worth its context budget.

Both burn context only when the agent judges it necessary.

### 5. One risk / failure mode

**Telemetry feedback loop consumes the agent’s context**.  
If the agent calls `budget_status()` after every dispatch, the returned dict (even if small) accumulates. A runaway loop of 100 dispatches + 100 telemetry calls adds ~20 KB. The design should encourage polling at strategic points (e.g., after a batch) and allow the agent to pass a `reset=True` flag to clear accumulated local telemetry state. Without this, the context‑preservation win is partially eroded.
