<!-- name=M05-ERROR-RECOVERY latency_ms=25179 error='' -->

## Score

| # | Dimension | Score | Justification |
|---|-----------|-------|---------------|
| 1 | **Correctness** | 2/5 | The EngineHealth schema bug silently swallowed every quarantine write — the exact failure this lens is designed to catch. It was fixed, but only because the audit sweep caught it; tests didn't. Now `preflight` and `today` both timeout = core commands produce no output. |
| 2 | **Robustness** | 1/5 | `preflight --skip-engines` and `today --since-hours 48` both hang to 30-second timeout with zero diagnostic. An `except Exception: continue` hid the schema bug for an entire wave. `preflight --fix` silently stashes the operator's in-progress work (W9 queued but not shipped). Three independent error-recovery paths fail silently or hang. |
| 3 | **Operator-usability** | 2/5 | The runbook exists, but if the operator runs `preflight` (step 1 of every autonomous-mode start) they stare at a blank screen for 30 seconds. `today` is the daily pulse — also dead. The operator cannot see their own system state through the two commands the runbook tells them to run first. |
| 4 | **Test discipline** | 2/5 | 1576 tests but none caught `except Exception: continue` masking a Pydantic validation error. No integration test runs `preflight --skip-engines` end-to-end under a timeout budget or it would have caught the hang. Mutation kill rate is healthy but the tested surface doesn't include the error-swallowing paths. |
| 5 | **Risk** | 5/5 | **Ship-blocker.** Two of the three most operator-facing commands are non-functional on HEAD. The operator literally cannot start their day. |

## Top Blocker

**Diagnose and fix the 30-second timeouts on `harness preflight --skip-engines` and `harness today`.** These are the first two commands the runbook tells the operator to run and both hang indefinitely until killed. Until they return real output, every other operator-readiness investment (runbook, status human, engines heal) is inaccessible because the operator can't even get past step 1.

## Verdict

**HOLD.** The two most operator-facing commands hang on invocation — the non-technical operator cannot run preflight or see today's status, which means they cannot safely enter autonomous mode or know whether their system is healthy.
