<!-- name=M06-AUDIT-GATE latency_ms=61596 error='' -->

## Score

1. **Correctness — 3/5**: Gate catches real regressions (PREFLIGHT-FIX STOP→PASS pinned a load-bearing schema bug) but ~30% of rows flip verdict with zero code change, so the output can't be trusted at face value.

2. **Robustness — 2/5**: Non-determinism is the definition of fragile. W8-ENGINES-HEAL went 0.58→0.85→0.68 across three sweeps on the same commit. No input stabilization (debounce, content-hash, diff-cap) fixes interpretive variance inside MiMo.

3. **Operator-usability — 2/5**: Non-technical operator must read three sweeps, apply ad-hoc "W6-PANEL precedent" to decide which STOPs are real, and manually accept-as-shipped. There's no `--avg-of-N`, no consensus score, no single number to act on.

4. **Test discipline — 2/5**: Zero tests for audit-gate verdict consistency. Nothing catches the gate itself regressing. Mutation canary (W9) would provide a deterministic regression signal independent of MiMo, but it's queued, not shipped.

5. **Risk — 3/5 (noise erodes trust)**: If the operator learns that 1-in-3 STOPs are coin-flips, the rational response is to ignore all STOPs — which makes the gate worthless. This trust-erosion is the real 30-day risk, not any individual false STOP.

**False-positive estimate**: ~30% — 3 of 10 rows show STOPs on code verified good in a prior sweep (no commit between sweeps 2→3). Two persistent STOPs (STOP-HOOK, AUDIT-PROMPT) appear legitimate and aren't counted as false positives.

**False-negative estimate**: ≥1 documented — the EngineHealth schema bug silently failing every quarantine write survived undetected across W6 and W7 audits. Rate is likely low (5–15%) but non-zero and unmeasurable without re-auditing prior waves against ground truth.

6. **Top blocker**: Ship **W9-MUTATION-CANARY** immediately. Three known-killer mutants per top module, daily Task Scheduler run, ≥1 test failure per mutant expected. This bypasses MiMo entirely and gives a deterministic, non-interpretable regression signal. One canary run per day makes the audit gate's non-determinism tolerable rather than fatal.

7. **Verdict**: **SHIP-WITH-FIXES.** The gate catches real regressions (PREFLIGHT-FIX is proof) but 30% noise + no deterministic fallback means it can't be the sole regression signal — ship mutation-canary as a mandatory W9-Blocker, not a nice-to-have.
