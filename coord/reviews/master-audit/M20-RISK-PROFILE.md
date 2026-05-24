<!-- name=M20-RISK-PROFILE latency_ms=31082 error='' -->

## Score

1. **Correctness**: 4/5 — Core flows work post-schema-fix, but persistent audit STOPs on STOP-HOOK and AUDIT-PROMPT indicate unresolved spec deviations.
2. **Robustness**: 3/5 — Silent quarantine failure (now fixed) exposed a fragility pattern: exceptions swallowed with `continue`. The `git_clean` preflight fail blocks autonomous mode; no auto-fix offered.
3. **Operator-usability**: 3/5 — Runbook and `harness today` are good, but non-deterministic audit flips (PASS→STOP with no code change) will confuse a non-technical operator expecting consistency.
4. **Test discipline**: 3/5 — 1576 tests and mutation gates are solid, but the audit gate itself is the primary regression detector—and it's non-deterministic. Tests don't catch audit-flip drift.
5. **Risk** (next 30 days): 4/5 — **Engine collapse is the top risk**: MiMo content filter blocks audit prompts; DeepSeek is now primary but has no proven fallback if it degrades. Key revocation by any provider could silently break dispatch. Cost overrun is secondary (~$0.03/wave, but Wave 10 scope is wide). Scope creep is medium—autonomous loop can keep adding rows without operator review.

**Top blocker**: Implement `W9-AUDIT-NONDETERMINISM-AVG` (`--avg-of-N`) before Wave 10 closes. The audit gate is the harness's quality backbone, and right now a single sweep has ~40% false-positive/negative noise. Averaging 3+ sweeps would collapse the noise floor and let operators trust the verdict. Without it, every future wave risks shipping on a STOP or holding on a false PASS.

**Verdict**: SHIP-WITH-FIXES. The harness is functional and the schema bug is fixed, but the audit non-determinism and lack of cross-engine fallback resilience mean the operator cannot fully trust the system's self-diagnosis yet.
