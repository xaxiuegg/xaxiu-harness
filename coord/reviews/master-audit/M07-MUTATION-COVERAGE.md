<!-- name=M07-MUTATION-COVERAGE latency_ms=27349 error='' -->

## Score — Mutation Coverage Reviewer

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3 | ≥3 gate is met for 5 tracked modules, but only 5 of ~20+ modules are tracked; W8 shipped 32 tests without re-running the sweep |
| **Robustness** | 2 | No mutation re-sweep in W8 despite code touching 6 new subcommands; canary deferred to W9; zero detection if a tracked module regresses |
| **Operator-usability** | 3 | Mutation data isn't operator-facing, but the audit gate it feeds is; operator can't assess whether mutations actually cover their risk surface |
| **Test discipline** | 2 | W7-MUTATION-ORCH is the only mutation-orchestration module; the 5-module table is a static artifact, not an enforced CI gate; gaps are invisible |
| **Risk** | 4 | W8 code landed in engines-heal, preflight-fix, stop-hook, audit-prompt, status-human, runbook — none re-validated by mutation sweep; ship-blocker if any of those modules dropped below the gate |

## Top blocker

**Surface untested modules.** Add a mutation-coverage manifest (e.g., `mutation_targets.yaml`) that lists every module with ≥3 known-killer mutants and its last-sweep SHA. Any module shipping code without a passing sweep must be auto-flagged. This transforms "5 modules pass" from a static snapshot into an enforced, auditable gate — and answers the operator's question: "what's CURRENTLY untested?"

## Verdict

SHIP-WITH-FIXES. The ≥3 bar is correct *for tracked modules* but the tracking surface is dangerously narrow (5 of 20+), W8 didn't re-sweep, and the deferred canary means regressions are invisible. Add the manifest + re-sweep W8-touched modules before closing.
