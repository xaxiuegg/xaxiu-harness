<!-- name=K07-DEAD-CODE latency_ms=100269 error='' -->

## Score
1. **Correctness**: 2 — Only ~60% of the ~30 listed verbs are live; the rest are stubs or pending-wave scaffolding (`swarm-verify` truncates mid-string, `observer` probe times out, W8-STOP-HOOK is persistently STOP).
2. **Robustness**: 2 — The `quarantined` write path was dead code masked by bare `except Exception: continue`; dead-engine handling fails silently without the schema patch.
3. **Operator-usability**: 3 — `today` and `preflight --fix` work, but the help surface mixes live features with unfinished scaffolding the non-technical operator cannot distinguish.
4. **Test discipline**: 2 — 1,576 tests missed the silently failing quarantine path, and W8 skipped the mutation sweep, leaving scaffolded modules unaudited.
5. **Risk**: 4 — A non-technical operator will invoke a stub verb or trust a broken hook; confusion or state corruption is a near-term ship blocker.
6. **Top blocker**: A `--stub-audit` gate that hides every CLI verb whose help text is truncated, times out in preflight, or references an unshipped Wave prefix.
7. **Verdict**: SHIP-WITH-FIXES — cull the dead verbs and hardened hooks before handing this surface to an operator.
