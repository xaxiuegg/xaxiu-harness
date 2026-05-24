<!-- name=M20-RISK-PROFILE latency_ms=38180 error='' -->

## Score
1. **Correctness** 3 — Core ops work, but 2 persistent audit STOPs and 3 non-det rows indicate spec-misalignment in the detection/audit layer.
2. **Robustness** 3 — Schema bug fix was load-bearing and good. However, MiMo audit non-determinism is a major fragility; the system's quality gate is probabilistic.
3. **Operator-usability** 4 — Runbook, `preflight --fix`, and `harness today` are solid wins. The persistent STOPs on the runbook and status human (non-det) suggest residual gaps.
4. **Test discipline** 4 — +32 tests, mutation canary running. The audit non-determinism itself is a testing problem that W9 aims to address.
5. **Risk** 4 — **Audit gate unreliability** is the top risk. 3 of 8 W8 rows have non-deterministic PASS/STOP verdicts with no code change, making the gate untrustworthy for holding the line. This directly threatens correctness.

**Top blocker**: Ship the `--avg-of-N` audit flag (W9-AUDIT-NONDETERMINISM-AVG) and use it as the default gate. Until the audit verdict is stable, the harness cannot be trusted to catch real regressions.

**Verdict**: SHIP-WITH-FIXES. The operator-readiness foundation is valuable, but the audit layer's non-determinism is a critical weakness that must be stabilized before claiming production readiness.
