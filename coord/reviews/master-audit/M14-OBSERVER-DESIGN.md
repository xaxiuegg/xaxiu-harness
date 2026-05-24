<!-- name=M14-OBSERVER-DESIGN latency_ms=45158 error='' -->

## Score

1. **Correctness (2/5)**: Observer probe times out in preflight — the detection layer isn't catching anything right now. The audit gate it feeds is non-deterministic: three rows flip PASS↔STOP with zero code change between sweeps, which means the observer's verdict is not grounded in stable criteria.

2. **Robustness (2/5)**: Observer timeout is a single point of failure for autonomous mode (preflight exit code 4 = hard blocker). MiMo content filter blocked every W9 audit until DeepSeek fallback landed — one fragility patched, but the structural non-determinism remains. `--avg-of-N` is a statistical band-aid, not a fix for inconsistent interpretation.

3. **Operator-usability (3/5)**: Preflight's observer timeout message gives actionable guidance (`harness observer scheduler-status`). But "Non-det" audit results in `harness today` are not operator-grade — a non-technical operator cannot act on "this flag flipped PASS↔STOP with no code change." The observer's 12 subcommands are developer-facing, not operator-facing.

4. **Test discipline (2/5)**: 41 observer tests from W20-OBSERVER exist, but none test the observer's own liveness or timeout behavior — exactly the failure preflight is catching. Non-determinism means even passing tests don't guarantee stable behavior across runs.

5. **Risk (3/5)**: Observer down → autonomous mode hard-blocked. Persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT confirm the detection layer has known blind spots. Not a ship-blocker in `review_each` mode, but autonomous loops are unreliable until fixed.

6. **Top blocker**: Diagnose and fix the observer probe timeout. Until the observer passes its own preflight health check, nothing else in the detection layer matters — the canary is dead. The 5-second timeout may simply be too tight, or the observer scheduler may not be armed; either way, this is the single artifact that lifts my score by ≥1.

7. **Verdict**: HOLD. Both load-bearing pillars of the detection layer — observer liveness and audit-gate determinism — are compromised. Fix the timeout, confirm observer cycles are actually running, then re-score.
