<!-- name=K20-NEXT-WAVE latency_ms=119545 error='' -->

## Score
1. **Correctness** — 3. Core operator commands (`preflight`, `today`) time out; two W8 rows remain persistent STOP and the MiMo gate is nondeterministic.
2. **Robustness** — 3. Silent `git stash` in `--fix`, blanket `except Exception: continue` masked the quarantine schema bug, and preflight hangs rather than degrading.
3. **Operator-usability** — 3. Runbook and `--human` exist but the operator cannot reliably run a morning pulse or safe preflight without hangs or data loss.
4. **Test discipline** — 4. 1576 tests pass and mutation gates clear, yet the quarantine path was uncaught until audit; deterministic canary is still deferred.
5. **Risk** — 4. Nondeterministic audit + missing canary + hanging core commands mean regressions can ship silently and readiness cannot be verified.

## Plus
6. **Top blocker** — W9-MUTATION-CANARY (detection). Stack-rank: detection > operator UX > engine reliability > v2 maturity > scope reduction. Detection is #1 because MiMo nondeterminism has already allowed persistent STOPs to ship and the operator cannot trust the audit gate to catch regressions.
7. **Verdict** — SHIP-WITH-FIXES. Readiness features exist but core CLI paths hang and the audit gate is unreliable, so Wave 9 must land the canary and timeout fixes before scaling usage.
