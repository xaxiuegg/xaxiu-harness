# Packet: Wave 2B.2 — Auto-fallback orchestrator

## Mission
Produce `src/harness/engines/dispatcher.py` — the routing + auto-fallback brain. Takes a packet + project name, picks an engine via routing rules + priority + lock + burst, calls dispatch, falls back on failure to a different engine (NEVER same), logs to history.db + jsonl_log, returns final result.

## Required API

```python
def dispatch_packet(
    *,
    project: str,
    packet_path: str,
    force_engine: str | None = None,
    force_model: str | None = None,
) -> DispatchResult: ...

@dataclass(frozen=True)
class DispatchResult:
    success: bool
    engine_used: str           # final engine that produced (or failed) the response
    fallback_chain: list[str]  # ordered list of engines tried, including the last
    text: str                  # engine response text (empty on total failure)
    error: str | None
    dispatch_id: str           # UUID written to history.db
```

## Dispatch flow

1. Validate `project` against `PROJECT_NAME_REGEX` (raise `ValueError`).
2. Load adapter via `adapters.loader.load_project_adapter(project)`.
3. Read packet file content (UTF-8, max 10 MB — raise on larger).
4. Pick initial engine:
   - If `force_engine`: validate it's in `SUPPORTED_BACKENDS`, use it (ignore routing rules but still respect LOCK refusal).
   - Else: walk `adapter.routing_rules` in order; first rule whose `if_` matches `packet_path` (glob via `fnmatch.fnmatch`) determines `backend` + `model`.
   - Apply priority override hierarchy from v1 §9: LOCK > BURST > per-project priority > global priority > rule. Read engine_health.json for current state.
   - If routing+priority say AVOID for the chosen engine AND another engine is eligible: skip to next-priority engine.
5. `insert_dispatch(...)` in history.db → returns `dispatch_id`.
6. Append entry to `state/active_dispatches.json` via `state.files`.
7. For each engine attempt:
   a. Call `engine.dispatch(packet_content, model, extra_args)`. Time it.
   b. On `EngineResponse.success=True` → success path: update history.db status to "success", remove from active_dispatches, write jsonl entry with outcome="success", return DispatchResult.
   c. On `EngineResponse.success=False`:
      - Choose next engine: from `SUPPORTED_BACKENDS` MINUS already-tried engines, respecting priority (HIGH > NORMAL > AVOID).
      - If no eligible engine remains: update history.db status to "all_fallbacks_exhausted", write jsonl with that outcome, return DispatchResult(success=False).
      - Else: `insert_fallback(dispatch_id, from_backend, to_backend, reason)`, write jsonl entry with outcome="fallback" + fallback_to=next, update engine_health.json status to "degraded" for the failing engine, set `current_backend` in active_dispatches, loop.

## Engine instantiation
Use `engines.concrete.get_engine(name)` — handles DPAPI/env-var resolution. Cache instances per dispatch (don't recreate for each retry).

## Priority enforcement (v1.2 amendments)
- Read engine_health.json once at start of dispatch via `state.files.read_engine_health()`.
- Sort eligible engines by priority value (HIGH > NORMAL > AVOID) using a stable sort that preserves insertion order within priority bucket.
- LOCK on engine X means: if X failed AND no other engine is in same lock-state, return failure (do NOT auto-fallback to a different lock state).
- BURST: if `engine_health[X].burst_until > now`, force route to X (overrides routing rules) — but if X fails during burst, still fallback to next.

## CRITICAL security requirements
1. NEVER log packet content — only `packet_path` goes into history/jsonl.
2. NEVER include API keys, response bodies, or request headers in `fallback.reason` field. Reason is the `EngineResponse.error` string (already audited safe: "HTTP <status>", "timeout", "network", "internal", "packet_trap").
3. `insert_routing_change` MUST be called when LOCK/BURST/priority is consulted (audit trail per MED-9). source="cli" since this is invoked from `harness dispatch`.
4. NEVER raise from `dispatch_packet`. All errors are returned as `DispatchResult(success=False, error="<short label>")`.
5. Max 1 retry per engine — never re-dispatch to same engine on failure.

## Implementation notes
- Module-level constant `MAX_PACKET_BYTES = 10 * 1024 * 1024` (10 MB).
- Use `fnmatch.fnmatch` for routing-rule glob matching (NOT regex — keep it simple).
- All state-file writes atomic per `state.files` contract.
- Update `engine_health.json` only on status transitions (don't re-write on every dispatch).

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/engines/dispatcher.py`. Target 300-450 lines. Type-hint everything. Imports: stdlib (`fnmatch`, `pathlib`, `time`, `typing`, `dataclasses`) + `from harness._constants import SUPPORTED_BACKENDS, PROJECT_NAME_REGEX` + `from harness.adapters.loader import load_project_adapter` + `from harness.engines.base import EngineResponse` + `from harness.engines.concrete import get_engine` + `from harness.state import files as state_files, db as state_db, jsonl_log`.

## Reference
- v1 spec §8 (Auto-Fallback procedure)
- v1 spec §9 (Priority/Burst/Lock hierarchy)
- v1.2 amendments HIGH-9 (closed log schema), MED-9 (routing_changes audit), HIGH-4 (command validation already in adapter loader)
- `src/harness/engines/concrete.py` (get_engine factory)
- `src/harness/state/files.py` (read_engine_health, update_engine_health, read/write active_dispatches)
- `src/harness/state/db.py` (insert_dispatch, insert_fallback, insert_routing_change, update_dispatch_status)
- `src/harness/state/jsonl_log.py` (write_log_entry)
- Per `spec/ACCEPTED_LIMITATIONS.md`: ACCEPT-2 (rotation lock deferred), ACCEPT-3 (broad except in concrete dispatch is upstream)
