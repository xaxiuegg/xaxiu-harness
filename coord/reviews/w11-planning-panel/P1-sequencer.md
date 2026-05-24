<!-- persona=P1-sequencer status=OK (34804ms) -->

# P1-sequencer

## 1. Top-line summary

Ship **W11‑AGENT‑INIT‑VERB** first — it creates the `.harness/` state directory, `.env`, adapter scaffold, and `STATUS.csv` that every subsequent row depends on. Ship **W11‑PYTHON‑SDK‑API** last — it wraps `dispatch`, `retrieve`, and `budget_status` and must wait for all core internals (frugal return, cache, telemetry) to stabilise. The critical path is `AGENT‑INIT‑VERB → DPAPI‑CROSS‑PLATFORM → CONTEXT‑FRUGAL‑RETURN → DISPATCH‑CACHE → RETRIEVE‑API → AGENT‑TELEMETRY → CROSS‑PLATFORM‑OBSERVER → PYTHON‑SDK‑API`, with engineering‑hygiene rows folded into the slack.

## 2. Concrete artifact

### (a) First row
| Row ID | Reasoning |
|--------|-----------|
| `W11-AGENT-INIT-VERB` | Creates `.harness/` state dir, `.env` file, adapter scaffold, `STATUS.csv`, and `CLAUDE.md` snippet. Every other row reads/writes these structures. No other row can execute without this foundation. |

### (b) Last row
| Row ID | Reasoning |
|--------|-----------|
| `W11-PYTHON-SDK-API` | Public API (`dispatch`, `retrieve`, `budget_status` + type stubs). Depends on `CONTEXT‑FRUGAL‑RETURN`, `DISPATCH‑CACHE`, `RETRIEVE‑API`, and `AGENT‑TELEMETRY` being stable. Also requires the `L5‑OUTPUT‑CONTRACT` to define SDK output shape. Shipping it last minimises API churn. |

### (c) Critical‑path chain
```
W11-AGENT-INIT-VERB
  │
  ├─ W11-DPAPI-CROSS-PLATFORM  (secrets needed for adapter config)
  │
  ├─ W11-CLAUDE-MD-TEMPLATE    (can follow immediately; no further deps)
  │
  └→ W11-CONTEXT-FRUGAL-RETURN  (DispatchResult default shape)
        │
        └→ W11-DISPATCH-CACHE    (uses content/adapter hash, depends on DispatchResult)
              │
              └→ W11-RETRIEVE-API  (needs frugal return + cache)
                    │
                    └→ W11-AGENT-TELEMETRY  (budget_status uses retrieve? no, but depends on record_dispatch)
                          │
                          └→ W11-CROSS-PLATFORM-OBSERVER  (needs dispatch/retrieve; cron alternative)
                                │
                                └→ W11-PYTHON-SDK-API     (final wrapper)
```
*Note: `W11‑ADAPTER‑VALIDATE‑JSON` can be inserted after `AGENT‑INIT‑VERB` (or anytime) — it only depends on adapter loading, not on the dispatch chain. It is **not** on the critical path.*

### (d) Parallelisable rows
| Parallel set | Rows | Rationale |
|--------------|------|-----------|
| **Set 1** (after init) | `W11-DPAPI-CROSS-PLATFORM`, `W11-CLAUDE-MD-TEMPLATE` | No cross‑dependencies; both read `.harness/` and `.env` created by init. |
| **Set 2** (after frugal return) | `W11-DISPATCH-CACHE`, `W11-AGENT-TELEMETRY` (partial) | Cache is independent of telemetry; telemetry only needs `budget.record_dispatch` (already exists). However, telemetry’s `dispatches_fired` field benefits from cache being present — defer telemetry until cache is done for accurate counts. |
| **Set 3** (after retrieve) | `W11-CROSS-PLATFORM-OBSERVER`, `W11-OBSERVER-WATCHDOG-RECOVERY` | Observer depends on retrieve; watchdog is a pure recovery mechanism that can be built alongside observer. |
| **Set 4** (any time) | `W11-HIDE-ADVANCED-VERBS`, `W11-L5-OUTPUT-CONTRACT`, `W11-MUTATION-PATTERN-EXPANSION`, `W11-AUDIT-ALL-W10-ROWS` | No runtime deps; best done in parallel with Set 1/2 to fill slack. `L5` must ship before `PYTHON-SDK-API`. `AUDIT` can run at any point but should be re‑run after the full wave ships. |

### (e) Go/no‑go gates between sub‑waves
| Gate | Condition | Action if blocked |
|------|-----------|-------------------|
| **11‑A → 11‑B** | `W11-AGENT-INIT-VERB` + `W11-DPAPI-CROSS-PLATFORM` + `W11-CLAUDE-MD-TEMPLATE` all ✅ | Block B until A shipped. A is small → ship A in one sprint. |
| **11‑B → 11‑C** | `W11-CONTEXT-FRUGAL-RETURN` + `W11-DISPATCH-CACHE` + `W11-RETRIEVE-API` all ✅ | C (telemetry/observer) uses `retrieve`; shipping C without B would cause missing features. |
| **11‑C → release** | `W11-PYTHON-SDK-API` + all 6 engineering‑hygiene rows ✅ | SDK is the final public contract. Hygiene rows must be done (especially `L5‑OUTPUT‑CONTRACT` and `AUDIT‑ALL‑W10‑ROWS`) to avoid regressions. |

## 3. Two open questions for the operator

1. **Should `W11‑ADAPTER‑VALIDATE‑JSON` be moved from 11‑C to 11‑A?** It only depends on adapter loading (exists now) and has no link to telemetry or observer. Moving it earlier would give validation coverage during the dispatch‑cache buildout. The current placement in 11‑C seems arbitrary.

2. **Do we allow early parallel shipping of `W11‑L5‑OUTPUT‑CONTRACT` with 11‑A?** The contract defines the DispatchResult shape that `CONTEXT‑FRUGAL‑RETURN` will implement. If we define the contract first, we reduce rework. Could we start L5 immediately after init? This is a design‑choice gate.

## 4. Alignment check

**Reorderings suggested:**
- Move `W11-ADAPTER-VALIDATE-JSON` from Wave 11‑C to Wave 11‑A (after init). It improves quality early and has no dependency on B or C.
- Move `W11-L5-OUTPUT-CONTRACT` to immediately after `W11-AGENT-INIT-VERB` (as a design specification). It should be completed **before** `CONTEXT‑FRUGAL‑RETURN` starts, not left to the end.
- Fold `W11-HIDE-ADVANCED-VERBS`, `W11-MUTATION-PATTERN-EXPANSION`, and `W11-AUDIT-ALL-W10-ROWS` into parallel slack during 11‑B buildout. They don’t need a dedicated sub‑wave.
- `W11-OBSERVER-WATCHDOG-RECOVERY` is correctly paired with `CROSS‑PLATFORM‑OBSERVER`; ship as a parallel set after `RETRIEVE‑API` is done.
- `W11-PER-CHECK-LATENCY-OBSERVABILITY` is pure engineering hygiene; it can be queued after `DISPATCH‑CACHE` is stable to measure cache hit latency. Defer to post‑B.

No rows are split or merged. The wave structure (A‑B‑C) is sound, but the engineering‑hygiene rows should be interleaved, not batched as a final cleanup.
