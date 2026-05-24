<!-- name=M04-OBSERVABILITY latency_ms=17927 error='' -->

## Score
**Correctness**: 4 – mostly does what it claims, but persistent audit STOPs and observer timeout show gaps.
**Robustness**: 3 – schema bug fixed, but observer timeout and non-deterministic audit sweeps indicate fragility under failure.
**Operator-usability**: 4 – runbook, `harness today`, and `preflight --fix` are clear, but observer timeout and missing `status --human` surface hurt.
**Test discipline**: 4 – 1576 tests, mutation kill rates above gate, but audit non-determinism suggests tests may miss regressions.
**Risk**: 3 – observer timeout and audit flakiness could erode operator trust, not a ship-blocker yet.

## Top blocker
Fix the observer probe timeout (`[!] observer             observer probe timed out (5s)`) so `harness preflight` passes cleanly and the operator sees a fully green gate.

## Verdict
SHIP-WITH-FIXES – the system is functional for a non-technical operator, but observable gaps (observer, audit flakiness) need closure before hands-off trust is earned.
