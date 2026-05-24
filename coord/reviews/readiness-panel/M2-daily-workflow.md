<!-- name=M2-daily-workflow latency_ms=15135 error='' -->

## Rubric

1. **Install** — 3/5: `harness install` + wizard exists, but `preflight` failures (dead engines, dirty git) require troubleshooting beyond "press a button."
2. **Daily run** — 4/5: `harness morning-brief` is the obvious start, but 2/6 preflight checks failing today adds cognitive load for diagnosis.
3. **Observe** — 5/5: `dashboard-serve` + `heartbeat` + `coord status` + `STATUS.csv` give clear, non-log-dependent visibility.
4. **Recover** — 3/5: CLI fix hints exist, but "rotate keys or quarantine" and "commit or stash" assume technical knowledge the operator lacks.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS.
   Reasoning: The core workflow (install, morning brief, observe dashboard, read STATUS.csv) is accessible. However, recovery from today's preflight failures (engine rotation, git operations) requires technical support. The system is ready for supervised use but not fully self-service for error recovery.

6. **Top 3 blockers:**
   1. `preflight` fix hints need a `--non-technical` mode that offers copy-paste commands or "ask for help" escalation.
   2. Intermittent dead engines (anthropic, gemini) suggest missing auto-quarantine or `harness engines --auto-fix`.
   3. No `harness morning-brief --summary` that outputs a plain-English "green/yellow/red" with next action.
