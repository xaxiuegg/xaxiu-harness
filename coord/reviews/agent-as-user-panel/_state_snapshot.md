## CLAUDE.md (top 3000 chars; what agent reads first)

```markdown
# CLAUDE.md — xaxiu-harness

You are working in the **xaxiu-harness** project at `D:\xaxiu-harness-standalone\` (migrated 2026-05-22 from `D:\Projects\xaxiu-harness\` — see MIGRATION.md).  Cross-project multi-engine LLM dispatch + monitoring tool, successor to `xaxiu-swarm`. **This is NOT the warehouse project** — different session scope.  This project has its own isolated Claude Code memory directory at `~/.claude/projects/D--xaxiu-harness-standalone/memory/` (43 entries) — warehouse-specific memory is intentionally NOT loaded here.

## Current state — v0.5 (v2 production-hardened + Phase-5 operator UX layered on top)

**v1 core** (single-Claude dev manager, in-session orchestration):

| Component | Files |
|---|---|
| Adapter schema, loader, NL→YAML | [src/harness/adapters/](src/harness/adapters/) |
| CLI — 22 top-level verbs (60+ subcommands incl. coord/observer/proxy/session/loop/budget/heartbeat/state/engines) | [src/harness/cli.py](src/harness/cli.py) |
| Engine ABC + 5 concrete (kimi/deepseek/anthropic/gemini/mock) + auto-fallback (mock excluded from prod chain) | [src/harness/engines/](src/harness/engines/) |
| State layer (JSON + SQLite + JSONL+redact; lazy init_db) | [src/harness/state/](src/harness/state/) |
| DPAPI secrets | [src/harness/secrets/dpapi.py](src/harness/secrets/dpapi.py) |
| HarnessError L1-L5 taxonomy | [src/harness/errors.py](src/harness/errors.py), [spec/errors.md](spec/errors.md) |
| Operator-modes (7 CLI flags + 11 YAML keys + OperatorSection) | [src/harness/operator/](src/harness/operator/), [spec/operator-modes.md](spec/operator-modes.md) |
| Status tracker primitive (#19) | [src/harness/status/](src/harness/status/), [spec/status-tracker.md](spec/status-tracker.md) |
| Observer primitive (#20) — armed via Task Scheduler | [src/harness/observer/](src/harness/observer/), [spec/observer.md](spec/observer.md) |
| Heartbeat + state-inspect | [src/harness/heartbeat.py](src/harness/heartbeat.py), [src/harness/state/inspect.py](src/harness/state/inspect.py) |
| Dashboard (FastAPI + WebSocket) | [src/harness/dashboard/](src/harness/dashboard/) |
| Loops productization — `harness loop init/tick/start/stop/status` | [src/harness/loops/](src/harness/loops/) |
| Replay (decision archaeology) | [src/harness/replay.py](src/harness/replay.py) |
| Budget meter + per-engine cost ledger | [src/harness/budget.py](src/harness/budget.py) |
| Session-handoff monitor (proactive transfer rec) | [src/harness/session/](src/harness/session/), [spec/session-handoff-monitor.md](spec/session-handoff-monitor.md) |

**v2 architecture** (planner / worker / proxy / coordinator — multi-agent w/ worktrees):

| Component | Files |
|---|---|
| **Spec** | [spec/multi-agent-harness-architecture.md](spec/multi-agent-harness-architecture.md) |
| v2/A — Stateful 4-key proxy + circuit breaker + auto-quarantine on flap | [src/harness/proxy/](src/harness/proxy/) |
| v2/B — Coord schemas + Planner + replan-from-failure + plan-from-NL | [src/harness/coord/schem
```

## harness --help

```
Usage: python -m harness [OPTIONS] COMMAND [ARGS]...

  xaxiu-harness: dispatch, observe, and retro across LLM engines.

Options:
  --mode [review_each|full_dev_authority|dry_run]
                                  Operator mode: review_each /
                                  full_dev_authority / dry_run.
  --escalation-threshold [L1|L2|L3|L4|L5]
                                  Only escalations at or above this level
                                  surface to operator.
  --engine-fill [aggressive|conservative|manual]
                                  Whether to fill idle Kimi slots with queued
                                  work.
  --max-parallel-supervisors INTEGER
                                  Max supervisors that may run in parallel
                                  within a tick.
  --explore-on-uncertainty [dispatch_alternatives|inline|ask_operator]
                                  What to do when the dev manager is
                                  uncertain.
  --observer-cadence-minutes INTEGER
                                  Cadence for the workflow-audit observer
                                  cycle.
  --profile [technical|non_technical]
                                  Operator profile (affects packet templates /
                                  error verbosity).
  --help                          Show this message and exit.

Commands:
  adapter              Manage harness adapters (generate, list, validate).
  budget               Dispatch budget + per-engine cost ledger.
  burst                Temporarily route all traffic to one engine.
  coord                Coordinator commands: plan, run, integrate, status.
  daily                W10-DAILY-QUICKSTART-VERB: operator-friendly daily...
  dashboard-serve      Run the operator-facing dashboard.
  dispatch             Execute a packet; auto-route if no backend is given.
  doctor               Preflight: check git, python, DPAPI, secrets,...
  engines              Query or modify the engine pool.
  engines-cooldowns    Show active engine cooldowns.
  engines-heal         W8-ENGINES-HEAL: one-command recovery for dead /...
  engines-reliability  Show / publish engine reliability ranking from...
  env                  Check which API keys are set (reports per-key +...
  env-wizard           W10-ENV-VAR-WIZARD: guided API-key population.
  heartbeat            Passive dev-manager liveness signal for the operator.
  init                 Create starter adapter YAML for a project.
  ins
```

## The pivot hypothesis (post-W10)

The non-technical chat-tier user fails at the first-run wall (2/10).
The CLI-literate user is at 6/10 (usable with runbook).  But the
THIRD user profile — an AGENTIC CODING AGENT cloning the harness
into a fresh project — may be the natural fit:

- Agent solves install / env-var / DPAPI friction in 2-3 tool calls
- Agent reads CLAUDE.md + dispatch-rules.md + memory files natively
- Agent uses STATUS.csv + audit gate + canary as scaffolding it
  doesn't have to re-implement
- Agent dispatches via xaxiu-swarm with full understanding of
  fallback chains

Per-new-project savings estimate (from observed harness build cost):
  - Engine routing: 4-8h
  - Audit gate: 3-6h
  - Task tracking (STATUS.csv): 2-4h
  - Cost ledger: 1-3h
  - Observer cycle: 4-8h
  - Mutation canary: 3-6h
  - Hooks / safety rails: 2-4h
  Total: 20-40h of scaffolding per fresh project

Test if this hypothesis holds.  Be skeptical.

## Operator framing (verbatim)

'if a non-technical user can not use the harness confidently, would
an agentic coding agent like claude or chatgpt would be able to run
it effectively. Like cloning a git repo down, and use the harness
rightaway. This replaced significantly the time of setting up all
the rules, agents, and establish the structures we need like status
csv agents routings etc'
