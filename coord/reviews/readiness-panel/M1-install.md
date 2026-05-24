<!-- name=M1-install latency_ms=16465 error='' -->

## Rubric
1. **Install (2/5)** – `harness doctor` shows env vars can be set via `env-wizard`, but the fresh-clone operator hits `preflight` blockers (git dirty, loop task not registered) that require understanding git and Task Scheduler beyond basic commands.
2. **Daily run (3/5)** – The `daily` verb exists, but the example `preflight` output shows a FAIL with instructions like "Commit or stash"—toil that requires git knowledge.
3. **Observe (4/5)** – `STATUS.csv`, `dashboard-serve`, and CLI commands (`heartbeat`, `morning-brief`) give visibility without reading raw files.
4. **Recover (4/5)** – Preflight errors have explicit "Run to fix" commands; `engines-heal` and `doctor` provide guided recovery.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The operator can run commands and follow guided wizards, but the initial `preflight` failure due to git state and unregistered loops would stop them cold. They’d need a one-time setup script that automates git commit and loop registration, or a human helper for that first hurdle.

6. **Top 3 blockers**
   - **First-run script missing** that auto-commits/stashes and runs `harness loop start` to clear common `preflight` fails.
   - **Git-clean check in preflight** is too strict for a fresh clone; it should allow a known-clean repo or provide a non-interactive fix command.
   - **Loop registration** must be part of `install` or `init`, not a manual step.
