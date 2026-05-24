<!-- name=M05-ERROR-RECOVERY latency_ms=23231 error='' -->

## Score

**Correctness**: 4/5 — Engine schema fix and preflight --fix work, but persistent audit STOPs on 2 rows suggest spec-compliance gaps in error recovery pathways.

**Robustness**: 3/5 — The schema bug fix shows critical error paths are now surfaced, but audit non-determinism could mask future recovery failures.

**Operator-usability**: 4/5 — `preflight --fix`, `engines-heal`, and runbook give clear recovery actions, but audit noise might undermine operator confidence.

**Test discipline**: 4/5 — +32 tests for W8, but mutation sweep not re-run means recovery-path regression detection is lagging.

**Risk**: 3/5 — Persistent audit failures could erode trust in error recovery guidance; operators may bypass recommended fixes.

**Top blocker**: Resolve the persistent STOP on W8-STOP-HOOK audit. If the audit gate itself can't reliably validate noise reduction, how can operators trust it to surface real error recovery needs?

**Verdict**: SHIP-WITH-FIXES — Core recovery flows work, but audit reliability issues need fixing before operators can confidently rely on the guidance system.
