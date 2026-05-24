<!-- name=M17-DOCS-ACCURACY latency_ms=24585 error='' -->

## Score

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 2/5 | Closeout claims `harness today` shipped; CLI help shows only `morning-brief` — doc and code disagree on the command name. |
| **Robustness** | 2/5 | Both documented-ref commands (`preflight --skip-engines`, `today`) timed out at 30s; no evidence they actually run. |
| **Operator-usability** | 3/5 | Runbook and human-readable status are described clearly in the doc, but if the commands don't execute, the operator has a playbook for tools that don't work. |
| **Test discipline** | 2/5 | 1576 tests asserted but unverifiable — the harness itself won't boot; mutation-kill table covers 5 modules with no breadth claim for the rest. |
| **Risk** | 3/5 | Doc-code mismatch on a primary operator-facing command (`today` vs `morning-brief`) will confuse a non-technical operator following the runbook literally. |

**Top blocker**: Reconcile the `harness today` claim in the closeout and runbook with the actual CLI verb (`morning-brief`); update either the doc or the CLI so they match, and verify the chosen command actually executes without timeout.

**Verdict**: SHIP-WITH-FIXES — the documentation fabricates a command name that doesn't exist in the CLI tree, and every tested harness invocation timed out, so nothing in the doc can be independently verified as functional.
