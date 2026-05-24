<!-- name=K4-cli-ergonomics latency_ms=88648 error='' -->

## Rubric
1. **Install** — 2. `env-wizard` and `doctor` are clear, but preflight hard-blocks on git cleanliness and loop registration, forcing git fluency and navigation of the `loop` vs `loops` naming split.
2. **Daily run** — 2. `daily` and `morning-brief` exist, yet the 22-verb surface offers no obvious sequencing guardrails; a non-technical operator cannot infer the morning ritual from `--help` alone.
3. **Observe** — 2. `dashboard-serve` and the `observer` group exist, but there is no top-level `status` verb; the operator must read `STATUS.csv` or know to invoke `coord status` and `observer scheduler-status`.
4. **Recover** — 3. `doctor`, `engines-heal`, and preflight fix-hints are strong, but recovery is fragmented across `loop start`, nested `observer` subcommands, and manual git steps.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The first-run wizards and preflight gate pattern are solid, but the 22-verb API surface is overwhelming, status is fragmented across files and nested subcommands, and hard blockers require git operations and precise verb recall that a runbook alone cannot bridge without L1 support.

6. **Top 3 blockers**:
   - **Top-level `harness status` verb**: A single daily, non-CSV, dashboard-in-terminal summary of loop, observer, and engine health (not buried under `coord`).
   - **`harness fix` meta-recovery verb**: One-command auto-remediation of preflight failures (git stash, observer restart, loop re-register) so the operator never touches git directly.
   - **Operator-slim CLI mode**: A `--simple` flag or role that hides the 15+ advanced verbs (adapter, lint-spec, lock, burst, etc.) and surfaces only daily, status, stop, and fix.
