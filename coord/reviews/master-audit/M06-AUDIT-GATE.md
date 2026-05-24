<!-- name=M06-AUDIT-GATE latency_ms=30628 error='' -->

## Score

**Correctness (3/5):** The gate correctly lifted W8-PREFLIGHT-FIX from STOP→PASS after the schema-bug fix — genuine true-positive detection. But 3/7 rows flipped verdict with **zero code change** between sweeps 2→3, which means the gate is right ~57% of the time on first read. A gate that's a coin-flip on 43% of rows isn't reliably correct.

**Robustness (2/5):** Non-determinism is the dominant failure mode. No `--avg-of-N` stabilization exists yet (queued W9-AUDIT-NONDETERMINISM-AVG, not shipped). The gate also has no self-calibration: it cannot report its own confidence interval or flag when a verdict is marginal (0.55–0.75 band). Three persistent/STOP rows (ENGINES-HEAL, STATUS-HUMAN, OPERATOR-RUNBOOK) produced 6 conflicting verdicts across 2 unchanged commits — that's the gate breaking, not the code.

**Operator-usability (2/5):** `harness today` surfaces "34 PASS, 27 STOP" with no resolution mechanism. A non-technical operator sees 44% STOP rate, can't distinguish signal from noise, and has no `audit explain` verb. The operator runbook says "every Wn row gets a MiMo audit before done" but doesn't tell the operator what to do when the audit contradicts itself.

**Test discipline (2/5):** Zero tests gate the audit gate's own stability. There's no golden-set regression test ("given this fixed commit, the gate must return ≥0.80 PASS"). Without that, the gate can drift unchecked. The 28 existing audit-engine tests validate plumbing, not verdict consistency.

**Risk (4/5):** Two risks compound: (1) operators learn to ignore STOPs → real regressions (like the W8 schema bug) get waved through; (2) the persistent STOP on W8-STOP-HOOK/AUDIT-PROMPT blocks those rows permanently even when improvements landed. Both are happening simultaneously right now.

**Top blocker:** Ship a golden-set stability test — 3–5 fixed commits with known-good verdicts, run the gate against them, fail CI if the gate flips. This is the minimum artifact to prove the gate's own integrity.

**Verdict:** SHIP-WITH-FIXES. The gate caught one load-bearing bug (schema/quarantine) proving it *can* work, but its 43% non-determinism rate means it's currently unreliable as a release gate — a regression-silent gate and a false-alarm gate produce the same operational outcome: operator distrust.
