<!-- name=M14-OBSERVER-DESIGN latency_ms=23818 error='' -->

## Score

| # | Dimension | Score | Justification |
|---|-----------|-------|---------------|
| 1 | Correctness | 3 | Observer runs, but two persistent STOPs are on the *detection layer itself* (STOP-HOOK, AUDIT-PROMPT) — the observer cannot cleanly pass its own audit. The `except Exception: continue` that silenced the schema bug for an entire wave proves the detection surface has blind spots. |
| 2 | Robustness | 2 | 3/7 audited rows flip PASS↔STOP with **zero code change between sweeps 2→3**. A detector whose verdict is a coin-flip on identical input is not robust — it's noise. The schema fix shows silent-failure patterns were load-bearing for weeks. |
| 3 | Operator-usability | 3 | The triage output is a confidence float with no guidance: non-technical operator sees `0.68 STOP` and has no decision procedure. No `--avg-of-N`, no "retry" button, no plain-language interpretation. `harness today` timed out in 30 s — operator can't even read the pulse. |
| 4 | Test discipline | 3 | 1576 passing tests exist, but the mutation canary (the deterministic regress check that bypasses MiMo) was *deferred* from W8. Observer's own behavior is untested for stability across repeated invocations. |
| 5 | Risk (30-day) | 4 | If the operator trusts a flippy audit gate, real regressions get waved through OR good work gets falsely STOP'd. Both erode authority credibility fast. |

**6. Top blocker:** Implement `W9-AUDIT-NONDETERMINISM-AVG` *before* re-running the readiness panel — an N=3 consensus where a row passes only if ≥2/3 sweeps return ≥0.70. This single change converts the audit gate from random signal to actionable triage and lifts correctness+robustness each by ≥1.

**7. Verdict:** **SHIP-WITH-FIXES** — The operator-readiness legs (preflight, runbook, heal, status-human) are genuinely load-bearing and should stay shipped, but the detection layer needs the averaging gate before the observer's verdicts carry operational weight.
