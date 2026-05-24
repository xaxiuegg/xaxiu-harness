<!-- name=M08-ENGINE-RELIABILITY latency_ms=35283 error='' -->

## Score

**Engine Reliability Reviewer — single-engine-collapse lens**

1. **Correctness** — 3/5: Schema bug fix (`EngineHealth` Literal missing `quarantined`/`recovering`) was load-bearing and resolved. But the quarantine flow was silently failing *every* write until W8 audit sweep caught it — meaning the production engine layer ran broken for potentially weeks. Correctness is now *claimed*, not yet *proven* across all states.

2. **Robustness** — 3/5: Post-fix, `engines-heal` walks the recovery chain correctly (dead→quarantined→recovering→blocked). Dispatcher fallback (W5-O: retry-on-different-engine) handles the primary collapse case. However, zero tests validate the end-to-end cascade: *engine goes down → alarm fires → heal quarantines → dispatcher skips → operator sees toast*. The `_check_dead_engines` excluding already-quarantined is correct, but `engines-heal` has no timeout/retry if `read_engine_health` itself fails during recovery.

3. **Operator-usability** — 3/5: `harness engines-heal` is a clean verb. The L4 toast fires. But non-det audit scores (PASS/STOP/STOP) mean *neither the operator nor I can trust that the module behaves as specified* — MiMo itself can't reach stable verdict on it.

4. **Test discipline** — 3/5: 1576 tests pass, dispatcher.py mutation kill-rate 17.30 is excellent. But the quarantine schema bug evaded all tests — `except Exception: continue` swallowed Pydantic rejection silently. No integration test exercises `preflight --fix` → `preflight --skip-engines` roundtrip and verifies the dead-engine warning *actually clears*.

5. **Risk** — 3/5: The non-determinism on W8-ENGINES-HEAL (the only row *directly* in my scope) means I cannot confirm the module is audit-clean. If a *second* engine collapses while the first is `recovering`, the current heal walk has no documented handling.

6. **Top blocker**: Add a **roundtrip integration test** — `read_engine_health` returns `{"status": "down"}` → `preflight --fix` quarantines → next `read_engine_health` returns `quarantined` → `engines-heal` marks `recovering` → subsequent preflight shows `[OK]`. This one test would have caught the schema bug *and* would anchor the non-det audit score.

7. **Verdict**: **SHIP-WITH-FIXES.** The schema fix is real and critical, but the engine layer's only proof-of-correctness is a single manual verification and three contradictory audit runs — one integration test closes the gap.
