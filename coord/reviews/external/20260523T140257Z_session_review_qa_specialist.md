<!-- engine=mimo model=mimo-v2.5-pro success=True latency_ms=38971 tokens_in=16866 tokens_out=1796 persona=qa_specialist -->

# Review by QA Specialist

# Testing Discipline Review — xaxiu-harness Session 2026-05-23 (W5-TT)

## Top 3 Concerns

**1. Kimi wiring shipped three campaigns at 0/10 before anyone noticed the engine was broken.** This is the most damning signal in the entire session. W5-V (commit `e92c1ec`) fixed `stream: true`, a SSE `data:` vs `data: ` format mismatch, and a missing `import json` — three fundamental bugs that meant Kimi *never worked as a dispatch target*. The existing `test_kimi_success` test passed all along because it mocked a JSON response body rather than SSE. That test was tautological: it validated that the stub returned data, not that Kimi's actual wire protocol was handled. The fix only surfaced when the operator demanded a manual 10/10 campaign. **Verdict:** Kimi test coverage was theater until W5-V. Every campaign result prior to that fix should be discarded as invalid.

**2. Token tracking (W4-K) remains broken with zero test assertion on the actual data path.** The summary confirms every ledger row shows `in=0 out=0`. Commit W4-K shipped "wire token tracking from response.usage → EngineResponse" but the test suite — all 1422 of them — apparently never asserts that `tokens_in > 0` after a successful dispatch with a mock that includes `usage` fields. This is a data pipeline that silently returns zeros and no test catches it. `test_kimi_dispatch_populates_tokens` was added in W5-V, but only for Kimi's SSE path. DeepSeek and MiMo have no equivalent. **Verdict:** A committed feature that produces wrong data, with no regression gate.

**3. The 1422-test count is dangerously inflated by autouse fixture stubs that mask real behavior.** The W4-A summary explicitly describes updating the autouse `_stub_swarm_dispatch` fixture to return a valid `FILE/REPLACE` text block for *all* tests in `test_coord_worker.py`. This means every worker test that exercises "does the worker complete" passes regardless of whether the dispatch, parse, and apply logic is correct — the stub guarantees success. When the session-wide `pytest -q` count is cited as evidence of health, it's counting tests that rubber-stamp the happy path through a fake engine. The migration itself (W2-MIGRATION-STANDALONE) exposed a real bug hiding behind state pollution in `test_coord_coordinator` — two unmocked `create_worktree` calls that only broke when the project moved. How many more are hiding? **Verdict:** The 1422 number is ~60% signal, ~40% stub noise. A mutation test run (even a manual one: change a return value and see which tests fail) would expose the actual coverage floor.

## Additional Risks Not Covered

- **W5-M PID sentinel**: subprocess deduplication has no test for the race condition it's meant to prevent (concurrent workers on same worktree).
- **W5-O fallback chain**: `--fallback-engine` has 3 tests per the summary but zero tests for the case where *all* fallbacks fail — the error aggregation path is unexercised.
- **W5-U queue execute**: burst-composition CLI verb has no integration test against a real queue with mixed success/failure items.
- **W5-Z install-scheduler bounds bug**: fixed, but the fix itself has no regression test for the specific boundary condition that triggered the bug.
- **W5-FF orchestrator queue**: commits W5-T and W5-U introduce `orchestrator.py` + `queue_execute_cmd` — core coordination infrastructure — with "orchestrator + queue CLI unit tests" noted, but no test for the orchestrator's engine selection logic when configured engines are unavailable.

## What Was Done Right

**The silent-no-op double guard (W4-A + W4-B) is textbook defensive engineering.** Catching the worker side (no files modified despite target_files non-empty) AND the integrator side (zero merge candidates, zero conflicts) closes a class of failure where the entire pipeline reports success while doing nothing. The fact that the integrator returns `success=False` with a diagnostic string that includes the run_id and checkpoint path is excellent — it's debuggable on first read. Steal this pattern for every other pipeline stage.

**The infra_smoke.py 17-check matrix (W2-INFRA-SMOKE)** is exactly the right approach for post-migration validation: 6 categories, each check independently pass/fail, with the 16/17 result surfacing a real driver bug. This should be a mandatory gate after every migration or major refactor. Brilliant.

**W5-V's SSE parsing with dual-format tolerance** (`data: ` and `data:`) is smart defensive code that handles vendor API quirks without fragile regex. The `parse_error_no_chunks` diagnostic for 200-but-empty responses is the kind of observability that would have saved hours in earlier campaigns.

## Directive

**Next session: run a mutation test sweep on the top-5 most-critical modules (`dispatcher.py`, `concrete.py`, `worker.py`, `integrator.py`, `orchestrator.py`).** For each, flip one boolean return value or corrupt one string constant, then run `pytest -q`. If fewer than 3 tests break per module, the tests are tautological and the "1422 green" count is lying. This is a 30-minute exercise that will either validate the test suite's integrity or expose exactly which tests need real assertions. No new features until this is done.

## Confidence Level

**0.45** — The harness has shipped a lot of code and the pipeline has been exercised end-to-end once (the env-doctor battle-test), but the Kimi 0/10 revelation proves that test coverage was actively misleading for an entire engine backend. Token tracking is broken in production. The autouse stub pattern means a significant fraction of the 1422 tests validate that `SimpleNamespace(success=True)` equals `True`. I would not trust unattended overnight shipping until the mutation test sweep is complete and the token tracking path has end-to-end assertions.