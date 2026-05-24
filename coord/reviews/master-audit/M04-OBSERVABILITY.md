<!-- name=M04-OBSERVABILITY latency_ms=21813 error='' -->

## Score

1. **Correctness**: 3/5 — Core status surfaces (STATUS.csv, CLI verbs) exist, but critical commands (`preflight`, `today`) timeout in the provided capture, breaking immediate operator observability.
2. **Robustness**: 2/5 — The 30s timeout on `preflight` and `today` renders them unusable under the snapshot conditions, a severe observability gap.
3. **Operator-usability**: 1/5 — The non-technical operator's primary windows into system state (`status --human`, `today`) are non-functional in the capture, forcing manual file digging.
4. **Test discipline**: 2/5 — 1576 tests pass, but the test suite did not catch the live-timeout of two core observability commands, indicating an integration or environment gap.
5. **Risk**: 3/5 — Without working daily pulse or preflight, the operator cannot detect stalls, cost spikes, or engine health issues in real-time, risking prolonged silent failures.

## Top Blocker

**Diagnose and fix the command timeouts.** The harness's observability promise (`harness today`, `harness preflight`) is currently hollow in the captured environment. Making these commands reliably complete in <30s is the single change that would lift operator-usability and robustness scores by ≥1.

## Verdict

**SHIP-WITH-FIXES.** The observability design is sound, but the captured execution failures make it non-functional for the operator today; the timeout root cause must be resolved before handoff.
