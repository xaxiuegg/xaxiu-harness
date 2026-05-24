<!-- name=K17-AUTHORITY-DISCIPLINE latency_ms=71760 error='' -->

## Score
1. **Correctness**: 3 — Persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT were overridden by precedent; the sole external check on dev authority is already compromised.
2. **Robustness**: 2 — Observer probe times out in preflight, MiMo flips PASS/STOP on identical code, and W8 skipped the full mutation sweep, so drift detection is unreliable.
3. **Operator-usability**: 4 — Runbook, `today`, and `preflight --fix` make daily ops accessible, yet the non-technical operator still cannot independently validate Claude's commits.
4. **Test discipline**: 3 — 1576 tests catch functional regressions, but coverage does not enforce boundaries on the dev-manager's unilateral authority.
5. **Risk**: 5 — Unilateral commit/push authority with a flaky, non-blocking observer is a ship-blocker; nothing stops a slow-motion authority failure.

6. **Top blocker**: Fix the observer probe timeout and make the audit gate truly blocking: require `--avg-of-3` MiMo runs ≥0.75 before any Wn row ships, with zero "accepted-as-shipped" waivers.
7. **Verdict**: SHIP-WITH-FIXES — Operator-facing features are ready, but the discipline layer is decorative until the observer is reliable and audit STOPs cannot be overridden.
