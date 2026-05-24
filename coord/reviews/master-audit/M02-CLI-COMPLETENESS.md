<!-- name=M02-CLI-COMPLETENESS latency_ms=49816 error='' -->

## Score

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 4 | Core verbs work as specced. Schema bug was load-bearing and got fixed. `doctor`/`preflight` split is semantically unclear in the help tree. |
| **Robustness** | 3 | Quarantine flow silently failed until caught; no `rollback` or `observer reset` for stuck states; `--skip-engines` is a manual escape hatch, not auto-degrade. |
| **Operator-usability** | 3 | `today`, `preflight --fix`, `engines-heal` are good on-ramps. But 22 top-level verbs + 60+ subcommands is high discovery friction for non-technical profile. `--profile non_technical` isn't the default. |
| **Test discipline** | 4 | 1576 tests, mutation kill rates ≥3 on all top-5 modules. Audit gate catches real regressions (schema bug). |
| **Risk** | 3 | Verb explosion makes the CLI hard to navigate blind. Missing lifecycle gap: no `rollback` for bad dispatches, no `upgrade` for harness updates, no key-rotation verb for the dead-engines path. |

## Top blocker

**Consolidate `doctor` into `preflight` and add `harness rollback`.** `doctor` and `preflight` are 80%+ overlapping (both check git, python, secrets); the split forces the operator to guess which one to run. A single `preflight` with `--fix` and `--quick` flags covers both. Meanwhile, the dead-engines fix mentions "rotate keys" but there's no `harness keys rotate` or `harness rollback <dispatch-id>` — a bad overnight dispatch currently has no undo path except `panic-dump` + ping engineering. Either verb closes a real lifecycle gap.

## Verdict

**SHIP-WITH-FIXES.** The CLI covers install → daily run → recover → retro → debug, but the 22-verb surface is bloated (4 verbs could be folded into `engines` subcommands; `doctor`/`preflight` should merge) and the missing `rollback` leaves a production hole that `replay` doesn't fill — `replay` reconstructs, it doesn't undo.
