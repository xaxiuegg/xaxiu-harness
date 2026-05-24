<!-- name=K11-AUDIT-NONDETERMINISM latency_ms=112933 error='' -->

## Score

1. **Correctness** — 3: Identical commits yield PASS↔STOP flips; the gate cannot reliably separate correct code from incorrect.
2. **Robustness** — 3: The harness tolerates runtime faults, but the audit layer fails under model jitter, producing fragile verdicts.
3. **Operator-usability** — 2: A non-technical operator sees binary PASS/STOP in `harness today` that swing 0.40→0.85→0.40 with no code change; the signal is unusable.
4. **Test discipline** — 4: Strong unit and mutation coverage catch code regressions, yet no test guards against audit-prompt variance.
5. **Risk** — 4: Alert fatigue from noise will desensitize the operator to real blockers or waste cycles chasing phantom gaps.

6. **Top blocker** — Ship `W9-AUDIT-NONDETERMINISM-AVG` as `--avg-of-N=3` with variance-aware labels (HARD PASS / HARD STOP / REVIEW) in `harness today`.
7. **Verdict** — SHIP-WITH-FIXES: The harness is operationally sound, but the audit gate's noise floor currently exceeds its signal, so it must be calibrated with averaged sweeps before PASS/STOP labels are actionable.
