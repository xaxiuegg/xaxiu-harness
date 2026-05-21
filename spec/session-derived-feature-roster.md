# Session-derived feature roster (2026-05-20 dev loop session)

Every directive the operator gave during the 2026-05-20 session must land as a real harness feature, not as ad-hoc behavior in the dev loop scaffolding. This document is the canonical checklist.

## Status legend

- ✅ Already in the harness (or scheduled in a queued/in-progress wave)
- 🚧 Specced, packet drafted, awaiting dispatch / merge
- 📋 To do — needs spec + packet + implementation

## Roster

| # | Feature | Origin directive | Target wave | Status | Notes |
|---|---|---|---|---|---|
| 1 | Full dev authority mode (auto-commit/push/dispatch) | "Override old rules, you have full dev authority" | Wave 7 | ✅ | Shipped in Wave 7/A+B: `--mode full_dev_authority` flag + `adapter.operator.mode` YAML key (W7/C added schema mirror) |
| 2 | L5-only escalation threshold | "Only request user input if face L5 error" | Wave 7 | ✅ | Shipped: `--escalation-threshold L5` flag wired to `apply_operator_flags` |
| 3 | Never-globally-halt + auto-retry escalation model | "I don't want to need to manually re-arm" | Wave 6 (runtime) + Wave 7 (config) | ✅ | manager.md Step 0 + `harness loop tick` runner read flags + auto-retry policy |
| 4 | Parallel supervisors with conflict-detection | "Supervisors should be able to run in parallel where possible" | Wave 6 | ✅ | `harness.loops.runner.tick` honours `write_set` from each supervisor for conflict detection; documented in manager.md |
| 5 | Engine slot-filling (Kimi aggressive, DeepSeek on-demand) | "Don't let Kimi sit idle... DeepSeek can be idle" | Wave 6 + Wave 7 | ✅ | `engine_slots` schema baked into adapter + state; `fill_policy` aggressive default for kimi/kimi-api, on-demand for deepseek |
| 6 | Multi-Kimi parallelism via xaxiu-swarm swarm subcommand | "Swarm has the ability to deploy multiple API calls" | Wave 6 | ✅ | Used routinely this session (Round 3 parallel 5/A+5/B; Wave 3+6A also dispatched in parallel) |
| 7 | swarm/kimi vs swarm/kimi-api distinction (agentic vs non-agentic) | "Refer to be able to differentiate kimi cli and kimi swarm" | Wave 6 | ✅ | Documented in dispatch-rules.md + memory `feedback_xaxiu_swarm_backend_agentic_differences`; routing uses it for packet format selection |
| 8 | Operator inputs → harness config | "All user guided input should be built into the harness... like --bare or --effort" | Wave 7 (foundation) + Wave 6 (extends) | ✅ | Wave 7/A+B+C shipped: 7 CLI flags + 11 YAML keys + Pydantic OperatorSection mirror |
| 9 | When-uncertain → dispatch more Kimi alternatives | "For where you uncertain, you can deploy more kimi agents" | Wave 7 | ✅ | `--explore-on-uncertainty dispatch_alternatives` flag shipped |
| 10 | Event-driven loop ticks (cadence as floor) | "If a task is finished... do not wait for the 30 min countdown" | Wave 6 | ✅ | manager.md "Event-driven, not cadence-driven" section + runner.tick consumes triggering events (task completion notification, cooldown lift, operator interject) |
| 11 | All features into harness (this directive itself) | "All features guided by user is to be incorporated to the final harness" | Wave 6 (acceptance criterion) | ✅ | This roster IS the verification list — all rows now ✅ |
| 12 | Autonomous dev loop pattern | "Create an autonomous loop to develop the harness" | Wave 6 | ✅ | Wave 6/A: `src/harness/loops/{state,runner,supervisors}.py`. Wave 6/B: `harness loop init/tick/start/stop/status` CLI verbs |
| 13 | Sub-loops + supervisor roles | "Treat claude sub agents as supervisors who control sub loops" | Wave 6 | ✅ (v1) | BaseSupervisor + 5 phase supervisors registered (TestingSupervisor mechanical; others NoOpSupervisor pending future iteration — extension point clean) |
| 14 | Observer system (workflow audit cycle) | "Arm observer for this session" | Wave 5.6 / Wave 6 | ✅ | `src/harness/observer/` + 12 `harness observer` subcommands + manager.md Step 0 + Windows Task Scheduler integration |
| 15 | 24/7 persistent mode via Windows Task Scheduler | "Allow the harness to be functioning when you sleep" | Wave 4 (installer) + Wave 6 (runner) | ✅ | `harness loop start --cadence-minutes N` registers `XaxiuHarnessLoopTick` via `src/harness/loops/scheduler.py`; same for observer (`install-scheduler`) |
| 16 | Process-improvement loop (5th supervisor) | "Incorporate and deploy a process improvement loop for this session; findings to be incorporated in final harness as well" | Wave 6 | ✅ (v1) | Prototype `coord/dev_loop/supervisors/process_improvement.md` still authoritative as procedure; productization deferred to future Wave 6 iteration (extension point in `harness.loops.supervisors` open via `_NoOpSupervisor("process_improvement")`). First-tick findings yielded this very row + 3 P1 fixes (parse-swarm-status integration + Kimi-CLI-incremental memory entry + 1200s timeout for multi-file packets). |
| 17 | Continuous heartbeat (operator passive status) | "Is dev manager up and active? Any loops idle" — operator shouldn't have to ASK | Wave 6 | ✅ | `harness heartbeat pulse/show` — Heartbeat schema + atomic-write + `format_for_human` with STALE-prefix detection |
| 18 | "Dev manager doesn't idle either" rule | "There is nothing stopping you from planning next steps or doing something else when testing supervisor conducts their work" | Wave 6 (manager runtime) | ✅ | manager.md "What you do NOT do" section codified. Memory `feedback_full_automation_until_wave_plan_empty` extends to: don't stop at task/wave boundary, only at kill conditions |
| 19 | **Canonical STATUS tracker as harness primitive** | "The status csv should be in the harness; it is our core feature to prevent session failures leading to corrupt chain" | **Wave 5.5** | ✅ | Shipped: `src/harness/status/` module + `harness status` CLI group with 7 subcommands. Pydantic-validated rows, atomic writes, dispatcher hooks (wave_id-gated), mtime canary. Spec: `spec/status-tracker.md`. |
| 20 | **Independent observer (check on dev-manager authority)** | "Has the harness have something similar to observer, so that it can question the authority and decision making of the dev manager in the loop" | **Wave 5.6** | ✅ | Shipped: `src/harness/observer/` module + 12 `harness observer` subcommands + manager.md Step 0 + Windows Task Scheduler integration. Cross-engine audit (DeepSeek when dev manager runs Kimi+Claude). Severity LOW/MED/HIGH/CRITICAL. Spec: `spec/observer.md`. |
| 21 | Operator dashboard (FastAPI + WebSocket) | "Operator needs passive view of harness state" | Wave 3 | ✅ | Shipped commit 71225ad: `src/harness/dashboard/` + `harness dashboard-serve`; uvicorn on 127.0.0.1:7878; WebSocket pushes every 5s; 15 dashboard tests. |
| 22 | Adapter templates + NL→YAML translator | "Operator shouldn't hand-write YAML; describe project in natural language" | Wave 5/A + 5/B | ✅ | Shipped: 6 templates under `adapters/templates/*.yaml` with `operator:` section + `src/harness/adapters/from_description.py` + `harness adapter from-description/list/validate` verb group. 23 NL→YAML tests. |
| 23 | Dispatch budget meter + per-engine cost ledger | "Track $/dispatch per engine so we can kill loops on cost" | Backlog (parked → shipped) | ✅ | Shipped commit b856131 (BUDGET-METER): `src/harness/budget.py` + `harness budget show/summary/set-cap/reset`; 22 tests. Kill-on-cost wiring is queued as KILL-CONDITION-WIRING. |
| 24 | Gemini 2.x engine adapter (triangulation engine) | "Need a third engine for ship-gate triangulation" | Backlog (parked → shipped) | ✅ | Shipped commit c96d6c4 (GEMINI-ADAPTER): Gemini concrete impl + boundary tests; reserved for triangulation when Kimi + DeepSeek already used (per dispatch-rules.md). |
| 25 | Replay CLI (decision archaeology) | "When a dispatch goes weird, I want to reconstruct the timeline" | Backlog (creativity) | ✅ | Shipped commit aecce9e (REPLAY-CLI): `src/harness/replay.py` + `harness replay` verb; joins DB dispatches + fallbacks with jsonl supplement; 10 tests. |
| 26 | Session-handoff monitor (proactive transfer rec) | "Long Claude sessions crash at ~52MB; recommend handoff before that" | Backlog (P1) | ✅ | Shipped commits e899be1 + 34e5cdd: `src/harness/session/` (monitor + recommender + signals + bootstrap) + `harness session check/bootstrap/ack/crisis-check/arm-crisis-check`; thresholds SOFT 8MB / STRONGLY 18MB / CRITICAL 35MB calibrated to operator's historic 52MB crash. Spec: `spec/session-handoff-monitor.md`. Manager.md Step 0.5 integrates the check. |
| 27 | Heartbeat + state-inspect (passive operator status) | "Is dev manager up? Any loops idle?" — operator shouldn't ASK | Backlog (P2) | ✅ | Shipped: `harness heartbeat pulse/show` + `harness state inspect` verbs; Heartbeat schema + atomic-write + STALE-prefix detection. 30 combined tests. |
| 28 | v2 architecture (Planner/Worker + worktrees + stateful proxy) | "4 Kimi keys → 24 concurrent slots; minimize context rot; resume from checkpoints" | v2/A-D | ✅ | Shipped commits d852889 + a863203 + a7ef925 + 3aec695: `src/harness/proxy/` (4-key proxy + circuit breaker) + `src/harness/coord/{schemas,planner,worker,worktree,checkpoint,coordinator,integrator,run_state}.py` + `harness proxy` (5 subcommands) + `harness coord` (6 subcommands incl. cleanup). 711/712 tests. Spec: `spec/multi-agent-harness-architecture.md`. First end-to-end run still queued (V2-FIRST-RUN). |
| 29 | Coord worktree/run-state GC verb | "Stale worktrees pile up; need a cleanup verb" | v2-polish | ✅ | Shipped commit 50aa65c: `harness coord cleanup` subcommand for worktree + run-state GC. |
| 30 | Loop-status surfaces observer + session flags | "Loop status should bubble up downstream signals, not just liveness" | v2-polish | ✅ | Shipped commit 43ad9e9: `harness loop status` surfaces observer HIGH/CRITICAL flags + session-handoff recommendation in one view. |
| 31 | Mock engine + v2 end-to-end smoke | "Need offline smoke for the whole pipeline" | Phase 4 | ✅ | Shipped commits 3003eeb + 9c05e95 (V2-MOCK-ENGINE + V2-FIRST-RUN): `src/harness/engines/mock.py` + `tests/test_coord_smoke_e2e.py` — caught 4 prod-blocking gaps (missing planner/worker adapters; no PROJECT_ROOT placeholder resolution; missing lazy init_db; stale ActiveDispatch literal). Mock excluded from auto-fallback chain via `_NON_PRODUCTION_BACKENDS`. |
| 32 | Worker actually runs + worktree creation | "Wire v2/C+D so coord run completes a real cycle" | Phase 4 | ✅ | Shipped commit 6bef07f (COORD-WORK-WIRE + WORKER-RUN-ENGINE + COORD-WORKTREE-CREATE): worker.run_worker dispatches FILE/REPLACE prompts to the configured engine and applies edits inside per-worker git worktrees; coordinator now calls create_worktree per task; checkpoints live under `runs/<id>/checkpoints/`. |
| 33 | Integrator merges worker branches | "Branches need to actually merge — that's the whole point" | Phase 4 | ✅ | Shipped commit 815de8b (INTEGRATOR-GIT-MERGE): `_merge_worker_branches` honours `plan.integration_strategy` (squash/merge/rebase); conflict aborts; IntegrationReport gained `workers_merged/skipped/conflicted`. 2 real-git tests. |
| 34 | Proxy auto-start from coord run | "Don't make me remember to launch the proxy first" | Phase 4 | ✅ | Shipped commit 53de7dc (PROXY-AUTOSTART): `src/harness/proxy/lifecycle.py` + `harness coord run --proxy auto/off/external` with try/finally cleanup. |
| 35 | Operator directives → first-class YAML | "Inputs I give in chat should become harness config" | Phase 4 | ✅ | Shipped commit 53de7dc (OPERATOR-DIRECTIVES-PROMOTION): three sub-schemas under `operator.*` — SessionHandoffThresholds, KillConditions, ProductionHygieneBalance — with pydantic constraints. Recommender accepts a HandoffThresholds dataclass for runtime override. |
| 36 | Kill conditions enforce | "Loops need budget hard-stops" | Phase 4 | ✅ | Shipped commit ab62db4 (KILL-CONDITION-WIRING): `runner._check_kill_conditions` reads `operator.kill_conditions` from adapter YAML, gates each tick against max_cost_usd / max_rows_dispatched / max_wallclock_minutes, records an L4 escalation + stops the loop on any breach. |
| 37 | Chat Observer (meta-audit of dev-manager) | "Observer should question Claude's authority too, not just project state" | Phase 5 | ✅ | Shipped commit ab62db4 (CHAT-OBSERVER): `src/harness/observer/chat.py::audit` flags dot_reply_loop / long_silence_no_commit / status_csv_missed against the session transcript jsonl. `harness observer audit-chat` CLI + (commit dd5e672) `--include-chat` auto-arm via Task Scheduler. |
| 38 | Live coord run telemetry (watch + list + retry) | "I shouldn't have to grep JSON files to know what a run is doing" | Phase 5 | ✅ | Shipped commits ab62db4 (COORD-LOG-STREAM) + f5ed5dd (COORD-RUN-LIST-VERB) + 445b55b (WORKER-RESUME-ON-RETRY): `harness coord {watch, list, retry}` cover live event tail, run enumeration, and resume-from-checkpoint. |
| 39 | Worker telemetry → budget meter | "v2 runs need to be visible to cost tracking" | Phase 5 | ✅ | Shipped commit f5ed5dd (WORKER-TOKEN-COST-TAG): EngineResponse gained tokens_used + cost_usd; worker.run_worker accumulates them across step dispatches and best-effort calls `budget.record_dispatch`. WorkerResult schema bumped with cost_usd field. |
| 40 | Dashboard v2 routes + WS embed | "Operator needs UI visibility into v2 runs" | Phase 5 | ✅ | Shipped commits d60923f (DASHBOARD-V2-ROUTES) + f5ed5dd (DASHBOARD-WS-V2-STREAM): `/v2/runs`, `/v2/runs/<id>/workers`, `/v2/proxy-state` JSON endpoints + `_snapshot()` now embeds `v2.runs` + `v2.top_run_workers` so the WS stream carries them. |
| 41 | Auto-fanout rule + scope checklist | "Wide packets time out; need an explicit split signal" | Phase 5 / process | ✅ | Shipped commit d60923f (PACKET-FANOUT-RULE): `## Auto-fanout` section in `coord/dev_loop/dispatch-rules.md` — 4 hard signals + 3 soft signals; rooted in empirical retry rate (supervisors-coverage 3 retries; V2-FIRST-RUN 4-gap discovery). |
| 42 | Post-integrate notify hook | "Run completion should signal external dashboards" | Phase 5 | ✅ | Shipped commit dd5e672 (COORD-NOTIFY-ON-INTEGRATE): `src/harness/coord/notify.py` writes notify.json atomically + optional webhook POST (urllib best-effort). Wired into integrator on both success + conflict paths. |
| 43 | Engine cooldown visibility | "I can't see why a backend got skipped" | Phase 5 | ✅ | Shipped commit dd5e672 (ENGINE-FALLBACK-COOLDOWN-VIZ): `harness engines cooldowns` reads `state.json::engine_cooldowns` and prints active windows + reasons. |

> Rows 1-20 mark the Wave 6 acceptance criterion. Rows 21-30 capture post-Wave-6 directives that landed during the 2026-05-20→2026-05-21 multi-session arc. Rows 31-43 capture the **production-hardening + Phase-5 polish arc** shipped 2026-05-21 in the autonomous session that started from operator's "Coordinator = Dev Manager, Planner = Loops Supervisors" directive — 22 production rows over ~10 sequential commits, tests 711 → 945+.

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
