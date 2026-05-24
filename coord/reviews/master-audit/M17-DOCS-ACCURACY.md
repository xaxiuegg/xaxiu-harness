<!-- name=M17-DOCS-ACCURACY latency_ms=32265 error='' -->

## Score

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3 | Closeout doc describes flows the code exhibits (prelight fix, engines-heal recovery); but W8-STOP-HOOK and W8-AUDIT-PROMPT hold persistent STOPs — auditor found gaps spec/* doesn't address. |
| **Robustness** | 3 | Schema-bug fix (EngineHealth Literal) is load-bearing and documented; but the spec/* files themselves may not enumerate `quarantined`/`recovering` states, leaving the next developer to re-break the same contract. |
| **Operator-usability** | 3 | OPERATOR_RUNBOOK exists, `today` prints blocks, `preflight --fix` is documented — but the `observer probe timed out` warning in the live output has no inline fix guidance; operator must hunt the runbook. |
| **Test discipline** | 3 | +32 net tests for 8 shipped rows (4 tests/row avg) is thin; some rows like W8-OPERATOR-RUNBOOK (docs-only) reasonably lack tests, but W8-STOP-HOOK claims 5 hook tests yet still holds persistent STOP — tests aren't catching the actual gap. |
| **Risk** | 4 | Two persistent STOPs + three non-det rows mean the doc/spec/code triangle has real divergence. The closeout itself admits "documentation lying" territory for STOP-HOOK's content-hash filter (present in code, not in spec). |

## Top blocker

**Audit the spec/* files against the HEAD code for the 5 W8-STOP-HOOK + W8-AUDIT-PROMPT rows.** The closeout text acknowledges the auditor found a code-side fix (content-hash filter) that the spec doesn't describe. Closing that gap — updating spec/ to reflect the actual debounce/hash/exclusion logic — would lift Correctness and Risk each by ≥1, and likely flip both persistent STOPs to PASS on the next audit sweep.

## Verdict

**SHIP-WITH-FIXES.** The code works (schema bug fixed, preflight quarantine confirmed), but two persistent audit STOPs flag genuine spec-accuracy drift that will re-trigger every wave until the spec/* files are reconciled with the commit-state.
