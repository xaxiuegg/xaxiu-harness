<!-- name=M2-daily-workflow latency_ms=23569 error='' -->

## Rubric

1. **Install — 4/5.** Doctor/preflight are comprehensive and readable; `install` verb exists. Deduction: the `git_clean` warning in preflight output would confuse a non-technical operator ("what do I do?"). Needs a `harness clean` or actionable message.

2. **Daily run — 3/5.** `morning-brief` is the right concept, but the operator's sequence isn't scripted or documented. CLI options (`--mode`, `--engine-fill`) add cognitive load. Needs a `harness daily` wrapper or a one-page "Your Morning" card.

3. **Observe — 3/5.** `dashboard-serve` exists but it's unclear if it shows real-time status without reading files. `morning-brief` gives a snapshot. STATUS.csv is human-readable but 296 rows are overwhelming. No `harness status --summary` for quick pulse.

4. **Recover — 4/5.** `engines-heal`, clear escalation thresholds (`L1-L5`), `preflight` with explicit `[!]` vs `[OK]`. `doctor` output is actionable. Deduction: recovery path for the `git_clean` warning is missing from CLI help.

5. **Hand to a non-technical operator today?** **WITH GUARDRAILS.** The system has strong diagnostics (`doctor`, `preflight`, `morning-brief`) and clear escalation definitions, but the daily workflow lacks a curated, minimal command sequence. A non-technical operator could survive with a one-page guide and the dashboard, but would likely stall on warnings (git_clean) or misconfigure flags (`--engine-fill`). Install is near-ready; runtime operation needs a guided "safe mode" default.

6. **Top 3 blockers:**
   1. **`harness daily` script** — a single command that runs preflight, morning-brief, and prints a 10-line summary with today's focus (from STATUS.csv `todo` rows). Moves daily run score +1.
   2. **`harness status --summary`** — dashboard/CLI verb showing: engine health, last loop run, active escalations, top 3 todo items. Moves observe score +1.
   3. **Actionable warnings** — every `[!]` in preflight/doctor should have a `fix:` hint or `harness fix <issue>` verb. Removes install/recover friction.
