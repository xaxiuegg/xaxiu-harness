# Session-derived feature roster (2026-05-20 dev loop session)

Every directive the operator gave during the 2026-05-20 session must land as a real harness feature, not as ad-hoc behavior in the dev loop scaffolding. This document is the canonical checklist.

## Status legend

- ✅ Already in the harness (or scheduled in a queued/in-progress wave)
- 🚧 Specced, packet drafted, awaiting dispatch / merge
- 📋 To do — needs spec + packet + implementation

## Roster

| # | Feature | Origin directive | Target wave | Status | Notes |
|---|---|---|---|---|---|
| 1 | Full dev authority mode (auto-commit/push/dispatch) | "Override old rules, you have full dev authority" | Wave 7 | 🚧 | `--mode full_dev_authority` flag; `adapter.operator.mode` YAML key |
| 2 | L5-only escalation threshold | "Only request user input if face L5 error" | Wave 7 | 🚧 | `--escalation-threshold` flag |
| 3 | Never-globally-halt + auto-retry escalation model | "I don't want to need to manually re-arm" | Wave 6 (runtime) + Wave 7 (config) | 🚧 | manager.md prototype; productize in Wave 6 |
| 4 | Parallel supervisors with conflict-detection | "Supervisors should be able to run in parallel where possible" | Wave 6 | 📋 | Prototyped in manager.md; needs productization |
| 5 | Engine slot-filling (Kimi aggressive, DeepSeek on-demand) | "Don't let Kimi sit idle... DeepSeek can be idle" | Wave 6 + Wave 7 | 🚧 | `engine_slots` schema in state.json + CLI flags |
| 6 | Multi-Kimi parallelism via xaxiu-swarm swarm subcommand | "Swarm has the ability to deploy multiple API calls" | Wave 6 | 📋 | Loop manager wraps swarm subcommand; spec needed |
| 7 | swarm/kimi vs swarm/kimi-api distinction (agentic vs non-agentic) | "Refer to be able to differentiate kimi cli and kimi swarm" | Wave 6 | 📋 | Routing engine reads packet contract; selects backend accordingly. Memory `feedback_xaxiu_swarm_backend_agentic_differences` |
| 8 | Operator inputs → harness config | "All user guided input should be built into the harness... like --bare or --effort" | Wave 7 (foundation) + Wave 6 (extends) | 🚧 | Wave 7 packet queued — Kimi implementing now |
| 9 | When-uncertain → dispatch more Kimi alternatives | "For where you uncertain, you can deploy more kimi agents" | Wave 7 | 🚧 | `--explore-on-uncertainty dispatch_alternatives` flag |
| 10 | Event-driven loop ticks (cadence as floor) | "If a task is finished... do not wait for the 30 min countdown" | Wave 6 | 📋 | Loop runner reacts to task-completion events |
| 11 | All features into harness (this directive itself) | "All features guided by user is to be incorporated to the final harness" | Wave 6 (acceptance criterion) | 📋 | This roster IS the verification list |
| 12 | Autonomous dev loop pattern | "Create an autonomous loop to develop the harness" | Wave 6 | 📋 | Prototype lives in `coord/dev_loop/` — productize as `harness loop` verbs |
| 13 | Sub-loops + supervisor roles | "Treat claude sub agents as supervisors who control sub loops" | Wave 6 | 📋 | 4 supervisor roles in prototype; user picks engine per supervisor in adapter YAML |
| 14 | Observer system (workflow audit cycle) | "Arm observer for this session" | Wave 6 | 📋 | Cycle script + Task Scheduler registration |
| 15 | 24/7 persistent mode via Windows Task Scheduler | "Allow the harness to be functioning when you sleep" | Wave 4 (installer) + Wave 6 (runner) | 📋 | `bin/register-dev-loop-task.ps1` in prototype |

## Verification (Wave 6 acceptance criterion)

When Wave 6 is declared done, **every row above must be ✅**. Items still 🚧 or 📋 indicate Wave 6 isn't complete. The operator should be able to ship this roster to a fresh xaxiu-harness deployment and have all directives respected without re-asserting them.

## Where each lands in the codebase (sketch)

```
src/harness/
├── operator/                  # Wave 7 — items #1, #2, #5, #8, #9
│   ├── modes.py
│   ├── config.py
│   └── flags.py
├── loops/                     # Wave 6 — items #3, #4, #6, #10, #11, #12, #13, #14, #15
│   ├── runner.py              # event-driven tick orchestrator (item #10)
│   ├── supervisors/           # base class + 4 default supervisors (item #13)
│   ├── manager.py             # parallelism + slot-fill (items #4, #5)
│   ├── escalations.py         # never-halt model + auto-retry (item #3)
│   ├── observer.py            # workflow audit cycle (item #14)
│   └── scheduler/
│       ├── windows_task.py    # Task Scheduler integration (item #15)
│       └── cloud_cron.py      # alt scheduler, post-v1
└── dispatcher/
    └── routing.py             # agentic vs non-agentic packet routing (item #7)
                               # swarm subcommand wrapping (item #6)
```

This roster is the source of truth for Wave 6/7 acceptance — update it as features land.
