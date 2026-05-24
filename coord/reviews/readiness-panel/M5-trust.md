<!-- name=M5-trust latency_ms=27125 error='' -->

## Rubric

1. **Install (4/5):** Preflight exits code 1 due to git untracked files. Doctor shows all OK. A non-technical operator could follow CLI commands but might be confused by the non-zero exit. Missing explicit "run `git clean`" guidance.

2. **Daily run (4/5):** `harness morning-brief` and `harness loop start` are clear. The operator can install via Task Scheduler. However, the expected morning sequence (brief → loop status → dashboard) isn't documented as a single "runbook" in the operator's language.

3. **Observe (3/5):** `dashboard-serve` exists, but the snapshot doesn't confirm it's designed for non-technical readability. `observer` output likely requires parsing logs. STATUS.csv is readable, but real-time loop health isn't surfaced in a simple CLI summary.

4. **Recover (3/5):** `engines-heal` and `preflight` are recovery commands. However, the git warning requires understanding version control. The `panic-dump` output likely contains traces. No clear "If you see error X, run command Y" table for common failures like engine cooldowns.

5. **Hand to a non-technical operator today?** **WITH GUARDRAILS.**
   The core CLI is robust with observer, heal, and status commands. A non-technical operator can install, start the loop, and check status. However, the lack of a plain-English runbook, non-obvious git warning resolution, and potential need to interpret observer logs for recovery means a technical "guardian" should be available for troubleshooting beyond basic operations.

6. **Top 3 blockers:**
   1. **Operator Runbook:** A `HARNESS_QUICKSTART.md` with the exact 3-command daily sequence (install → start → observe) and explicit remediation for the git warning.
   2. **Recovery Guide:** A `harness recover --what` command or a section in the runbook mapping `preflight` warnings and common `observer` flags to specific CLI fixes.
   3. **Simple Health Dashboard:** Enhance `harness loop status` or add `harness health` to output a plain-text summary: loop state, last observer pass/fail, and any active cooldowns—no file digging required.
