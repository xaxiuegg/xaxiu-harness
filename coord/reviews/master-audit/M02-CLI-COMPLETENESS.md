<!-- name=M02-CLI-COMPLETENESS latency_ms=38801 error='' -->

## Score

**Correctness: 4/5** — The verb tree covers every lifecycle phase. The quarantine schema bug (silently swallowed `quarantined` status) was load-bearing and is fixed. `doctor` and `preflight` overlap with no documented distinction — one is redundant or orphaned.

**Robustness: 3/5** — The W8 schema fix (`EngineHealth` Literal missing `quarantined`/`recovering`) means *every* prior `preflight --fix` quarantine silently failed. That's a foundational robustness gap that existed for weeks. Fixed now, but it reveals insufficient integration-test coverage on the write-path.

**Operator-usability: 3/5** — `today`, `env-wizard`, `preflight --fix`, and the runbook are strong. But 40+ verbs with three overlapping execution paths (`loop`, `orchestrator`, `coord`) and two overlapping health checks (`doctor`, `preflight`) overwhelm the non-technical operator. No lifecycle grouping in `--help`.

**Test discipline: 4/5** — 1576 passing, mutation kill ≥3 on all top-5 modules. Audit-gate policy is enforced. Persistent STOPs on STOP-HOOK and AUDIT-PROMPT suggest the audit infrastructure itself needs dogfooding.

**Risk: 2/5** — No ship-blocker. The non-determinism is accepted with a queued mitigation. Missing verbs (`uninstall`, `rollback`, `pause`) are convenience gaps, not safety gaps.

**Top blocker** — **Collapse `doctor` into `preflight` or document the distinction in `--help`.** Add lifecycle groupings to the help output (`## Setup`, `## Daily`, `## Recover`, `## Debug`). The non-technical operator's first 10 minutes with `harness --help` should map to the runbook's sections. Today it's an alphabetical wall of 40+ verbs with no entry point.

**Verdict: SHIP-WITH-FIXES.** The CLI is functionally complete across the lifecycle, but verb-tree sprawl (three execution verbs, two preflight verbs, no grouping) and the now-fixed-but-revealing quarantine schema bug indicate the operator-facing surface needs a focused deduplication pass before handoff.
