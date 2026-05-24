<!-- name=K3-failure-modes latency_ms=131162 error='' -->

## Rubric

**First-month failure modes**
1. **Preflight halts on `git_clean` warning.** Error: visible (`3 untracked files`) but not actionable. Recovery: not obvious (stash? delete?). → Ping engineering.
2. **Engine proxy fail-closed / key exhaustion.** Error: absent or engineering-level (W9-PROXY-FAILURE-MATRIX is todo). Recovery: undocumented. → Ping engineering.
3. **Task Scheduler silent death.** Error: none; preflight only checks “armed,” not last-run health. Recovery: unclear. → Ping engineering.
4. **Engine quarantine cascade.** Error: preflight notes dead engines. Recovery: `engines-heal` exists but is not suggested in output. → Ping engineering.

1. **Install** — 2. Preflight exits 1 on a soft git warning with no `--fix` or plain-language hint, stalling non-technical users.
2. **Daily run** — 3. `morning-brief` exists, but hidden Task Scheduler dependencies and lack of a single curated checklist add toil.
3. **Observe** — 2. STATUS.csv mixes 296 wave and dispatch rows; no evidence the dashboard is deployed for non-technical readability.
4. **Recover** — 1. Critical failures (proxy, engine death, silent exceptions) lack CLI-guided remediation or operator-facing runbooks.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. Core verbs and checks exist, but the first month will repeatedly surface ambiguous preflight halts, opaque proxy failures, and silent scheduler deaths that require engineering escalation because self-service recovery paths are not yet wired or documented.

6. **Top 3 blockers**
   - `harness preflight --fix` or guided plain-language remediation for git/stash warnings.
   - Shipped W9-PROXY-FAILURE-MATRIX plus `harness engines` surfacing one recommended recovery verb when quarantined.
   - Operator-filtered status view (e.g., `harness status --operator`) that hides raw dispatch logs and surfaces only health and next actions.
