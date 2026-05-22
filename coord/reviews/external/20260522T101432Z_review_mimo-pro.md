<!-- engine=mimo model=mimo-v2.5-pro success=True latency_ms=34383 chars=4218 -->

## 1. Was the inline drift mostly Claude's role-discipline gap, or also a packet/dispatcher gap?

**~80% discipline, ~20% systemic.** Claude had the memory rule (`feedback_plan_first_dispatch_default`) and still chose inline fixes across *three successive waves* (8 + 4 + 4 defects). That's a pattern, not a momentary lapse. However, the dispatcher contributed: (a) `force_engine` doesn't short-circuit — it falls through the full chain, so dispatching "feels slow" compared to inline, which biases Claude toward doing it himself; (b) budget meter is silent (`no dispatches`), so there's no visible accounting that would trigger a self-correction ("I've dispatched 0 of 12 items — am I following protocol?"); (c) there's no structural enforcement gate (e.g., a pre-commit hook or action-classifier that blocks non-dispatch CLAUDE.md writes). The rule is advisory-only. Fix the dispatcher to be fast-and-visible and the discipline problem shrinks — but Claude still must *choose* to dispatch, and three consecutive waves of not doing so is a role-discipline failure.

---

## 2. Throughput ceiling

**~12–18 completed features in 8 hours**, assuming:
- Each feature → 1 planning dispatch + 1–2 implementation packets + 1 validation = **~3 dispatches/feature**.
- Each dispatch costs ~90 s round-trip (20 s Claude packet-write + 60 s engine + 10 s merge). With force_engine no-fallback, that's 90 s. With fallback chain, 120–180 s.
- Claude processing/summarization between dispatches: ~2–3 min overhead.
- **Per-feature wall-clock: ~5–7 min.**
- 480 min ÷ 5–7 min = 68–96 dispatches. At 3 dispatches/feature → **~22–32 features raw**, but subtract ~30–40% for failures, retries, mis-scoped packets, and engine disconnects on large payloads → **12–18 shipped features**.

Today's actual: ~8 defect-fixes done inline + 3 dispatched = ~11 effective items. Inline was faster per-item but didn't scale the team. With perfect dispatch discipline, **2× today's output is realistic, not 10×.**

---

## 3. Memory + hook scoping fix

**Per-project memory directories.** `~/.claude/projects/D--Projects/xaxiu-harness/memory/` + `~/.claude/projects/D--Projects/warehouse/memory/` with a shared `common/` dir symlinked into both. Justification: (1) tagged-filter is fragile — you're parsing prose tags on 51 entries, and Claude will still load all files; it's a runtime tax with no guarantee of correctness. (2) Migration to a new folder is just per-project dirs plus a move; do them together. (3) Per-project dirs give you automatic scoping with zero per-session cost, eliminates the 27-entry warehouse leak *by construction*, and lets hooks reference only the memory dir they're scoped to — so `check-csv-stale.sh` lives in `warehouse/memory/hooks/` and never fires in xaxiu sessions. One migration script: `split_memory_by_project.py` reading the first-line tag convention already in the entries.

---

## 4. Packet shape evolution — next failure mode

**Multi-packet dependency chains at the per-feature level.** Today's failure mode was single-packet size (10 KB → 60 s server disconnect). Read-set embedding + anchor-windowing fixes that by keeping review packets under ~4 KB. The *next* break: a feature that requires **sequential packets** (spec → implementation → integration-test) where the second packet depends on the first engine's output. Claude currently has no mechanism to pipeline or chain dispatches — each is fire-and-forget with a summary wall. When feature N's implementation packet needs feature N-1's validation result *in its context*, Claude will either (a) inline the dependency (recapitulating today's drift), (b) dispatch with stale context (correctness failure), or (c) block on the prior dispatch then manually copy the output (losing all speed). The missing primitive is a **dependency-DAG dispatch mode** where packet B can declare `depends_on: [packet_A.output]` and the dispatcher queues/wires it automatically.

---

## 5. One-line top change to ship next

**Move `dispatch_packet`'s `record_dispatch()` call from after the try/except into the *main path* before the engine loop, and log `(dispatched, engine, outcome)` — so budget metering is real and Claude sees a running tally per session.**