<!-- name=M08-ENGINE-RELIABILITY latency_ms=36072 error='' -->

## Score

1. **Correctness — 4/5.** The schema bug fix (`7081d93`) unblocked the entire quarantine flow; manual verification confirms it works. But `preflight --skip-engines` timed out at 30s, so I cannot independently verify end-to-end engine-health state today.

2. **Robustness — 3/5.** The `except Exception: continue` that silently swallowed every quarantine write is a systemic anti-pattern; one instance was load-breaking, and no one audited whether the same pattern exists elsewhere in the engine layer. A single engine collapsing mid-dispatch falls back (dispatcher.py mutation kill rate 17.30 is strong), but the engine-heal command itself hit a 30s timeout in this snapshot — recovery may hang under real failure.

3. **Operator-usability — 4/5.** `harness engines-heal` is a single verb; the runbook links to it. `harness today` timed out, so the operator currently has no plain-language engine-health pulse — but the intent is sound and the timeout is likely environmental.

4. **Test discipline — 3/5.** 1576 tests, +32 this wave, dispatcher at 17.30 kill rate — excellent. But the schema bug lived through multiple waves undetected precisely because tests asserted on return values, not on `engine_health` disk state. W8-ENGINES-HEAL is audit-non-deterministic (STOP twice of three), meaning even the auditor isn't confident tests cover the recovery transitions.

5. **Risk — 3/5.** One engine dying is the exact scenario this layer exists for. The quarantine path now works, but the `recovering → up` promotion is untested in the snapshot (preflight timeout), and the silent-exception pattern may mask other failures that only surface under real engine collapse.

6. **Top blocker.** Grep `except.*continue` across all `engines/` and `dispatch` paths; convert every instance to at minimum `logger.warning` with the caught exception, or surface it via the L4 alarm. One such instance already silently broke quarantine for weeks — the same pattern elsewhere is the highest-probability next failure.

7. **Verdict — SHIP-WITH-FIXES.** The schema fix is real and load-bearing, but the silent-exception sweep is prerequisite to trusting the engine layer under a single-engine collapse — which is its primary job.
