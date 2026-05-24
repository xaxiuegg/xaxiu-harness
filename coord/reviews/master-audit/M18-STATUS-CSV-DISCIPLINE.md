<!-- name=M18-STATUS-CSV-DISCIPLINE latency_ms=30397 error='' -->

## Score

| Criterion | Score | Justification |
|---|---|---|
| **Correctness** | 3 | STATUS.csv *tracks*, but 3 rows shipped with non-det audit verdicts violate the "every Wn gets a MiMo audit before done" policy — ship status contradicts policy. |
| **Robustness** | 2 | No staleness detection; a row can sit `todo` forever or flip audit verdicts indefinitely with no automated flag or operator-visible warning. |
| **Operator-usability** | 3 | Notes are long and commit-SHA-heavy; a non-technical operator skimming 309 rows gets signal-buried in noise. Header says "~280 rows" — file is 309. |
| **Test discipline** | 2 | No test asserts STATUS.csv schema invariants (valid transitions, non-empty updated-date, audit-verdict consistency). `W9-ONCOMMIT-HOOK-CRLF` touches the CSV hook but doesn't validate semantic integrity. |
| **Risk** | 3 | Tracker drift is silent — next wave inherits stale `shipped` rows whose audit verdicts are "Non-det (PASS once, STOP twice)". Confidence compounds, not resets. |

## Top blocker

**Enforce a hard rule: rows cannot be marked `shipped` unless their audit verdict is deterministic PASS (≥2 consecutive sweeps, same commit).** Add a `harness status lint` subcommand that checks: (a) every `shipped` row has an associated PASS verdict in its note or audit log, (b) no row's `Updated` timestamp is >72h stale for `in_progress` rows, (c) header row count matches actual row count. The 3 non-det rows (ENGINES-HEAL, STATUS-HUMAN, OPERATOR-RUNBOOK) should be re-classified `shipped-pending-audit` until the `--avg-of-N` gate (W9) lands and confirms them. This single lint would lift Correctness from 3→4 and Risk from 3→2.

## Verdict

**SHIP-WITH-FIXES** — The tracker *exists* and *renders*, but it's drifted into "commit every action, audit later" territory; the non-det shipped rows and the stale header count are live symptoms, not hypotheticals.
