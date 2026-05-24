## Current state (post-W10, commit 0c99386)

- 1810 tests pass + 6 skip + 3 deselected slow
- 10 waves shipped (W1-W10) over ~3 weeks of operator-driven work
- Test count growth: started ~1000 → 1810 over 10 waves
- Wave rate: ~8-14 rows per wave, ~2-5 commits per wave, ~1-2 weeks/wave

## Honest rating today
- ChatGPT-tier user (treats LLMs like ChatGPT/Claude Desktop): **2/10**
- CLI-literate non-Python user: **6/10**

## Operator profile
The operator is NON-TECHNICAL.  Can:
  - Edit YAML, run CLI commands, manage Windows Task Scheduler
  - Read STATUS.csv

Cannot:
  - Author Python
  - Debug Python tracebacks
  - Read engine logs and root-cause issues

User stated framing: 'just happen to thought of it as Claude Code
or ChatGPT the like' — i.e. type, get answer.

## What's been built (just the headline features)

ENGINE/DISPATCH LAYER:
- Multi-engine dispatch with auto-fallback (Kimi, DeepSeek, MiMo,
  Anthropic, Gemini, Mock)
- Per-key circuit breakers + auto-quarantine on flap
- 4-key proxy pool for Kimi (24 concurrent slots)
- Cost ledger per dispatch
- Adapter-driven routing (YAML config per project)

OPERATOR UX LAYER (W8-W10):
- harness daily (W10): one-verb morning routine
- harness env-wizard (W10): guided DPAPI key setup
- harness preflight (W6+): readiness gate with PASS / PASS-WITH-
  WARNINGS / FAIL verdict (W10)
- harness today (W8): plain-language daily pulse
- harness morning-brief (W4): overnight summary
- harness profile set/show (W10): persisted operator profile
- harness status list --recent N (W10): recent-rows view
- harness engines-heal (W8): one-command engine recovery
- preflight --fix (W8): auto-remediation (no longer silently stashes
  per W10)
- Operator runbook + verdict semantics table + DPAPI section

DETECTION/SAFETY LAYER (W6-W9):
- MiMo audit gate (--avg-of-N for non-determinism)
- Mutation canary (rotating 4-module warm tier)
- Mutation manifest (3-tier coverage tracking)
- Silent-except lint baseline (locked at 0 broad swallows)
- Atomic state writes + advisory file locks
- Redaction patterns consolidated + integrity tests
- Proxy failure matrix (12-row spec + tests)
- CRLF hook fix
- Stop-hook noise reduction

COORD V2 (multi-agent worktree):
- Planner → Worker → Coordinator → Integrator pipeline
- Worktree-isolated parallel workers
- Checkpoint + progress-stream + heartbeat
- 13 coord subcommands (plan/run/work/retry/integrate/replan/etc)

WHAT'S STILL MISSING (W11+ candidates queued):
- Standalone installer (.exe / .msi) — currently git clone + pip install
- harness start wizard (single-command first-run path)
- Dashboard as default surface (currently opt-in localhost FastAPI)
- Morning email brief
- Cost visibility widget
- Hide advanced verbs (--advanced namespace)
- L5 escalation output contract
- Observer watchdog self-recovery
- Mutation pattern expansion (async/await flips for observer/cycle)


## W10 readiness panel verdict (just the headline)

0/10 YES, 8/10 WITH GUARDRAILS, 2/10 NO.  Every NO-vote reviewer cited the first-run preflight failure (git_clean blocker) as unresolvable for a non-technical user.


## W10 master-audit panel (40 reviewers)

0 SHIP-AS-IS, 5 HOLD, 35 SHIP-WITH-FIXES.  No regressions post-W9 (was 0/4/35).  Convergent themes: structural first-run gap, observer fragility, latency observability, cost surfacing.
