# CLAUDE.md — xaxiu-harness

You are working in the **xaxiu-harness** project at `D:\xaxiu-harness-standalone\` (migrated 2026-05-22 from `D:\Projects\xaxiu-harness\` — see MIGRATION.md).  Cross-project multi-engine LLM dispatch + monitoring tool, successor to `xaxiu-swarm`. **This is NOT the warehouse project** — different session scope.  This project has its own isolated Claude Code memory directory at `~/.claude/projects/D--xaxiu-harness-standalone/memory/` (43 entries) — warehouse-specific memory is intentionally NOT loaded here.

## First action in any fresh session / clone / worktree (READ FIRST)

**Always run this single command first, before anything else:**

```bash
pip install -e . --quiet && python -m harness today && python -m harness plan show
```

Why this exact form:

- **`pip install -e .`** — idempotent (~1s if already done, ~30s cold fresh clone).  Required because a fresh clone has no runtime deps importable (`click`, `httpx`, `pypdf` etc.).  W13-INSTALL-VERIFY's CI gate proves this works on a fresh venv.
- **`python -m harness`** (not bare `harness`) — universal post-install form that works regardless of whether your shell's PATH includes Python's Scripts/bin directory.  This is the Windows + Git Bash gotcha: `pip install` creates `harness.exe`, but Git Bash often doesn't have the Scripts dir on PATH, so `harness today` still returns `command not found` even after a successful install.  `python -m harness` sidesteps PATH entirely — it works whenever `import harness` works.

The bare `harness` form works only AFTER both (a) `pip install -e .` and (b) your shell's PATH includes the Python Scripts directory.  When uncertain, prefer `python -m harness`.

**Recommended minimal session-resume prompt** (works against any clone/worktree state on any OS):

> *"Resume xaxiu-harness. Run `pip install -e . --quiet && python -m harness today && python -m harness plan show`. Propose next action."*

If `pip install -e .` is genuinely impossible (no network, locked-down env) BUT deps are somehow already importable, `PYTHONPATH=src python -m harness <verb>` is the last-resort form.

---

## What this project is (load-bearing framing)

xaxiu-harness is the operator's command surface and observability layer for delegating dev work to multiple LLMs.  **Three operating modes**, low → high autonomy:

1. **Cross-engine panel** (`harness ask`) — fire the same question at 3+ engines in parallel; compare answers side-by-side.  $0.20-0.30 per panel via Pattern B routing.
2. **Agentic dev manager** — single Claude session orchestrating in real time, with full dev authority, captured directives, forensic audit trail, per-engine budget caps.
3. **Multi-agent coordinator** (`harness coord`) — Planner/Worker pattern with isolated git worktrees, stateful 4-key proxy with circuit breaker + auto-quarantine, replan-from-failure, integration phase.  The mode that justifies the proxy + worktree + multi-key infra.

Underneath: cross-platform key resolution, JSONL audit ledger with redaction, replay, budget meter, observer flags, FastAPI dashboard.  "Ask 3 LLMs" is the lowest-autonomy surface, not the project's scope.  Operator-facing docs in [docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md), agent-facing in [docs/AGENT_REFERENCE.md](docs/AGENT_REFERENCE.md).

## Current state — v0.5 (v2 production-hardened + Phase-5 operator UX layered on top)

**v1 core** (single-Claude dev manager, in-session orchestration):

| Component | Files |
|---|---|
| Adapter schema, loader, NL→YAML | [src/harness/adapters/](src/harness/adapters/) |
| CLI — full verb list via `harness --help` / `harness capabilities` (live count beats stale doc numbers; P6 audit fix 2026-05-27) | [src/harness/cli.py](src/harness/cli.py) |
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
| v2/B — Coord schemas + Planner + replan-from-failure + plan-from-NL | [src/harness/coord/schemas.py](src/harness/coord/schemas.py), [src/harness/coord/planner.py](src/harness/coord/planner.py) |
| v2/C — Worker + worktree + checkpoint + progress-stream + heartbeat | [src/harness/coord/worker.py](src/harness/coord/worker.py), [src/harness/coord/worktree.py](src/harness/coord/worktree.py), [src/harness/coord/checkpoint.py](src/harness/coord/checkpoint.py) |
| v2/D — Coordinator + Integrator + canceller + notify hook + `harness coord` CLI (12 subcommands) | [src/harness/coord/coordinator.py](src/harness/coord/coordinator.py), [src/harness/coord/integrator.py](src/harness/coord/integrator.py), [src/harness/coord/canceller.py](src/harness/coord/canceller.py), [src/harness/coord/notify.py](src/harness/coord/notify.py) |
| v2/E — Operator UX: dashboard /v2/* JSON + HTML detail + cost panel + WS embed | [src/harness/dashboard/v2_routes.py](src/harness/dashboard/v2_routes.py), [src/harness/dashboard/app.py](src/harness/dashboard/app.py) |
| v2/F — Production hardening: MockEngine + V2-FIRST-RUN smoke + budget meter wired to worker telemetry | [src/harness/engines/mock.py](src/harness/engines/mock.py), [tests/test_coord_smoke_e2e.py](tests/test_coord_smoke_e2e.py) |
| Operator-config sub-schemas (session_handoff / kill_conditions / production_hygiene_balance) | [src/harness/adapters/schema.py](src/harness/adapters/schema.py) |
| Spec lint (pre-flight) | [src/harness/lint.py](src/harness/lint.py) |
| Replay (extended to v2 coord runs) | [src/harness/replay.py](src/harness/replay.py) |
| Chat observer (meta-audit of session transcript) | [src/harness/observer/chat.py](src/harness/observer/chat.py) |

`harness coord` subcommands: `plan`, `plan-from-description`, `run`, `work`, `retry`, `rerun-failed`, `integrate`, `replan`, `status`, `watch`, `list`, `cancel`, `cleanup`.

Smoke test: `PYTHONPATH=src python -c "from harness.cli import cli; print(sorted(cli.commands.keys()))"`.
Tests: run `python -m pytest tests/ -m "not slow" -q --tb=no` for the live count.  (P6 audit fix 2026-05-27: removed the stale "990/990" snapshot — the suite has grown well past that and hard numbers in this file go stale faster than commits land.)

## Operator authority + escalation (load-bearing)

Per operator directive 2026-05-20 ([feedback_xaxiu_harness_full_dev_authority](https://github.com/xaxiuegg/xaxiu-harness/) in memory):

- **Full dev authority** within xaxiu-harness scope. Commit, push, dispatch, install dependencies, modify code without per-action confirmation. Supersedes the prior 30 LOC ceiling **for this project only** — other projects (warehouse) still under [feedback_claude_strategic_role].
- **Escalate to operator ONLY for L5 errors.** Definition in [reference_xaxiu_harness_error_taxonomy] — L5 = FATAL = operator action required (e.g. DPAPI unreadable, git auth lost). L1-L4 stay autonomous; the loop self-heals via cooldowns + auto-retry. The loop never globally halts on L5 — only the affected phase pauses with exponential backoff.

## Engine routing (read [coord/dev_loop/dispatch-rules.md](coord/dev_loop/dispatch-rules.md) for the full table)

- **swarm/kimi** (xaxiu-swarm wrapping Kimi-Code CLI subprocess) → agentic, applies in-place edits. Use for multi-file refactors, in-place edit packets.
- **swarm/kimi-api** (xaxiu-swarm + Kimi REST) → non-agentic. Single text response to deliverable path. Use for FIND/REPLACE blocks or full-file output the integrating supervisor parses.
- **swarm/deepseek** (xaxiu-swarm + DeepSeek REST) → non-agentic. Same as kimi-api. V-file-spanning, math/schema-correctness, novel-feature drafting. Pair with `--no-thinking` for surgical patches.
- **Never** dispatch to `--backend claude`; never use Claude Agent sub-agents for ship-gate audits ([feedback_no_claude_swarm_worker]).
- **Multi-packet dispatch**: prefer `xaxiu-swarm swarm --max-concurrent N packet1 packet2 ...` over N separate `dispatch` calls.
- **Mandatory flags**: `--timeout 420+` (swarm/kimi), `--deliverable`, `--add-dir`, `--context-file CLAUDE.md`, `--progress 30`.
- **Cooldowns**: on any engine failure, set 60min cooldown for swarm/kimi, 15-30min for non-agentic backends. Fall back to alternate engine, don't retry the same one until cooldown lifts.

## Parallelism + slot-filling

- **Supervisors run in parallel** where their write-sets don't intersect. See [coord/dev_loop/manager.md](coord/dev_loop/manager.md) for the conflict-detection rules.
- **Engine slot policy**: keep `swarm/kimi` slots full (subscription cost) per [coord/dev_loop/dispatch-rules.md]. `swarm/deepseek` stays idle unless needed (per-API cost).
- **Wave-splitting**: when a wave touches N independent modules, split into N packets, fan out via `xaxiu-swarm swarm --max-concurrent N`.
- **When uncertain → deploy more Kimi.** Dispatch 2-3 packets with alternative framings rather than agonizing alone.

## Dev loop (autonomous)

[coord/dev_loop/](coord/dev_loop/) is the prototype autonomous loop driving this project. Shared state in `state.json`. Four supervisors (creativity/developing/testing/integrating) per [supervisors/](coord/dev_loop/supervisors/). Manager logic in `manager.md`. Engine routing rules in `dispatch-rules.md`. Currently runs as in-session ScheduleWakeup ticks; will run via `bin/register-dev-loop-task.ps1` (Windows Task Scheduler) when operator activates persistent mode.

## Memory entries this session inherits

Load these from `~/.claude/projects/D--Projects/memory/` (operator's Claude memory) at session start:

- `feedback_xaxiu_harness_full_dev_authority` — authority + escalation rule
- `reference_xaxiu_harness_error_taxonomy` — L1-L5 + domain + code scheme
- `feedback_xaxiu_swarm_backend_agentic_differences` — swarm/kimi vs api backends
- `feedback_operator_inputs_become_harness_config` — Wave 7 origin + uncertainty rule
- `user_non_technical_role` — operator profile (still applies for end-user-facing tools)
- `feedback_multi_session_scoping` — don't cross into warehouse

## Session discipline

- DeepSeek and api-backend Kimi output via `--deliverable` path; integrating supervisor parses and applies.
- Every wave landing → tests must remain green; CI on GitHub Actions gates regressions.
- Cooldowns are operational rules, not punishments — respect them; do other work meanwhile.
- Don't touch warehouse files or its STATUS.csv from this session.
