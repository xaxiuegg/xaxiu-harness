<!-- name=K1-onboarding-friction latency_ms=162950 error='' -->

## Rubric

1. **Install** — 2. The fresh-clone path forces ~8 operator decisions (which of 3 docs, install method, global flags, `doctor` vs. `preflight`, how to fix `git`/ `pytest`/ dead-engine failures); `preflight` fails on `pytest_cache` and `git_clean` with fixes requiring Python/git skills, and dead-engine remediation points to unreadable JSONL logs.
2. **Daily run** — 3. `harness morning-brief` is a single obvious verb, but the first-run sequence is gated by red `preflight` checks that a non-technical operator cannot clear autonomously, creating toil before the briefing ever runs.
3. **Observe** — 4. `morning-brief`, `dashboard-serve`, `STATUS.csv`, and `coord status` provide rich, engine-log-free visibility; the operator never needs to open `runs/` files by hand.
4. **Recover** — 2. Remediation hints (`fix: Inspect state/engine_performance_log.jsonl`, `Run pytest, fix failures`) demand traceback literacy and log analysis; there is no `harness recover` automation to bridge the gap.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. A non-technical operator can consume `morning-brief` and `STATUS.csv` once the system is green, but cannot independently clear `preflight` (pytest failures, dead-engine triage, git stashing) or install Python dependencies. They need a technical owner to prep the environment and handle any red preflight state.

6. **Top 3 blockers**
- `--operator` preflight mode that skips dev-only gates (`pytest_cache`) and auto-quarantines dead engines instead of asking the operator to read JSONL.
- Single-page onboarding doc that collapses 20+ CLI verbs into an exact 3-command path: `install` → `doctor` → `morning-brief`.
- `harness recover` command that automates safe fixes (git stash, engine quarantine) and presents plain-language confirmation instead of tracebacks or raw state files.
