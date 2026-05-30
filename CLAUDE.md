# CLAUDE.md — xaxiu-harness

You are working in the **xaxiu-harness** project at `D:\xaxiu-harness-standalone\` (migrated 2026-05-22 from `D:\Projects\xaxiu-harness\` — see MIGRATION.md).  Cross-project multi-engine LLM dispatch + monitoring tool, successor to `xaxiu-swarm`. **This is NOT the warehouse project** — different session scope.  This project has its own isolated Claude Code memory directory at `~/.claude/projects/D--xaxiu-harness-standalone/memory/` (57 entries as of 2026-05-28; check `MEMORY.md` index for the live count) — warehouse-specific memory is intentionally NOT loaded here.

## ⚠ Path A — the harness is being retired to a thin core (2026-05-30, operator directive)

The operator chose **Path A**: keep the subscription keys (Claude / Kimi-Code / MiMo Token-Plan are UA-gated → CLI-only, so off-the-shelf gateways like LiteLLM/OpenRouter can't use them), trim bespoke infra, and lean on the vendor CLIs + native Claude Code skills. For NEW cross-vendor work, prefer the native skills over the big harness verbs:

| Want | Use (Path A) | Retiring |
|---|---|---|
| Cross-vendor compare | **`/compare`** (MiMo + Kimi + Claude via CLIs, side-by-side) | `harness ask --engines` / `--panel` |
| Web-grounded MiMo / headless browser | **`/mimo-research`** (MiMo via `opencode serve` + Playwright MCP — verified headless) | — |
| Cross-vendor fact-check / audit | **`/harness-audit`** | — |
| Agentic multi-file dispatch | **`xaxiu-swarm --backend kimi`** + the **Kimi CLI** | harness `coord` / `dispatch` |

Engine-headless ground truth (every Windows trap): **`C:\Users\xaxiu\ENGINE-HEADLESS-PLAYBOOK.md`**. The `/compare` + `/mimo-research` skills are user-level (`~/.claude/skills/`) and reuse `C:\Users\xaxiu\oc-mimo-runner\mimo-headless.ps1`. `harness ask` / `proxy` still work and stay for now; `coord` / `dashboard` / `observer` / `loops` are trim candidates. **Don't add new bespoke machinery — wire native features to the CLIs.**

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

## Current state — v0.6.x (v2 production-hardened + Phase-5 operator UX + W14 agentic-operator/security PM-2026-05-28 layered on top)

Current version: see `pyproject.toml` + `src/harness/__init__.py::__version__` for the live value (these are the only sources that don't go stale — every other count in this doc is a snapshot).


**v1 core** (single-Claude dev manager, in-session orchestration):

| Component | Files |
|---|---|
| Adapter schema, loader, NL→YAML | [src/harness/adapters/](src/harness/adapters/) |
| CLI — full verb list via `harness --help` / `harness capabilities` (live count beats stale doc numbers; P6 audit fix 2026-05-27) | [src/harness/cli.py](src/harness/cli.py) |
| Engine ABC + 6 concrete (kimi/deepseek/anthropic/gemini/mimo/qwen) + MockEngine + auto-fallback (mock excluded from prod chain) | [src/harness/engines/](src/harness/engines/) |
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
| v2/D — Coordinator + Integrator + canceller + notify hook + `harness coord` CLI (13 subcommands as of 2026-05-28; check `harness coord --help` for the live count) | [src/harness/coord/coordinator.py](src/harness/coord/coordinator.py), [src/harness/coord/integrator.py](src/harness/coord/integrator.py), [src/harness/coord/canceller.py](src/harness/coord/canceller.py), [src/harness/coord/notify.py](src/harness/coord/notify.py) |
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

## Engine routing (read [coord/dev_loop/dispatch-rules.md](coord/dev_loop/dispatch-rules.md) for the live table — rewritten 2026-05-26 for Pattern B)

**Live source of truth**: `harness engines compatibility-matrix` (Phase 1.2 shipped 2026-05-28) renders an N×M table of every engine × every consumption surface (CLI/SDK/proxy/swarm); `harness engines describe <name>` returns per-engine metadata in one call.  Below is a short orientation, NOT the canonical reference.

Three engine families currently in active rotation:

- **Pattern A (direct HTTP)** — `deepseek`, `mimo`, `qwen`, `anthropic`, `gemini`.  Each speaks its native REST.  Use for routed `harness ask` + audit + dispatch.
- **Pattern B (Claude-Code subprocess)** — `mimo-via-claude`, `kimi-via-claude`, `deepseek-via-claude`, `qwen-via-claude`.  Spawns Claude Code with a per-provider config, TOS-compliant for User-Agent-gated providers (MiMo Token Plan, Kimi Code subscription).  **DO NOT hand-roll a custom shim** — these wrappers exist precisely so you don't have to.
- **Swarm subprocess (xaxiu-swarm)** — `swarm/kimi` (agentic, applies in-place edits), `swarm/kimi-api` / `swarm/deepseek` (non-agentic, write to `--deliverable` path).  Sibling repo; clone separately.  Multi-file refactors + multi-turn tool use.
- **Never** dispatch to `--backend claude`; never use Claude Agent sub-agents for ship-gate audits ([feedback_no_claude_swarm_worker]).
- **Multi-packet dispatch**: prefer `xaxiu-swarm swarm --max-concurrent N packet1 packet2 ...` over N separate `dispatch` calls.
- **Mandatory flags**: `--timeout 420+` (swarm/kimi), `--deliverable`, `--add-dir`, `--context-file CLAUDE.md`, `--progress 30`.
- **Cooldowns**: on any engine failure, set 60min cooldown for swarm/kimi, 15-30min for non-agentic backends. Fall back to alternate engine, don't retry the same one until cooldown lifts.

## Native Claude Code features vs. the harness (routing — 2026-05-28)

Native CC features (subagents in `.claude/agents/`, `/goal`, Dynamic Workflows) are the **orchestration front-end**.  They are single-vendor (Claude-only), so they MUST NOT answer cross-vendor work from Claude alone — that would orphan the harness's reason to exist ([feedback_native_features_wire_to_harness] in memory).  **Mental model: native = front-end; harness = the cross-vendor engine it calls.**

- **Claude-only work** (single-session ideation, local test runs, in-session "keep working until X") → native is fine.  `/goal <condition>` (CC ≥ v2.1.139) replaces the bespoke "keep going" loop for IN-SESSION persistence; its condition should shell out to `python -m harness session ok-to-stop` so the cross-engine / `wave_plan` gate stays authoritative (`/goal` has no visibility into STATUS.csv).
- **Cross-vendor work** (ship-gate audits, second opinions, multi-engine panels, multi-file dispatch) → MUST route through the harness.  Delegate to the `cross-vendor-panel` subagent, which shells out to `python -m harness ask --panel`/`--audit`, or use `xaxiu-swarm dispatch`.  Never substitute a single-vendor Claude answer for a cross-vendor verification.
- **Subagents that touch dispatch** (the developing/integrating roles) are BRIDGE subagents: `tools: Bash` → `python -m harness …` / `xaxiu-swarm …`.  The cross-vendor dispatch + worktree + ship-audit logic stays harness-driven; the `tick()` write-set conflict-detection + merge has no native equivalent and stays in the harness loop.

Native subagents shipped so far: `cross-vendor-panel` (bridge), `creativity` + `testing` (read-only native conversions of the dev_loop supervisors).  `developing`/`integrating` stay harness-driven (cross-vendor) until wired as bridge subagents.

## Parallelism + slot-filling

- **Supervisors run in parallel** where their write-sets don't intersect. See [coord/dev_loop/manager.md](coord/dev_loop/manager.md) for the conflict-detection rules.
- **Engine slot policy**: keep `swarm/kimi` slots full (subscription cost) per [coord/dev_loop/dispatch-rules.md]. `swarm/deepseek` stays idle unless needed (per-API cost).
- **Wave-splitting**: when a wave touches N independent modules, split into N packets, fan out via `xaxiu-swarm swarm --max-concurrent N`.
- **When uncertain → deploy more Kimi.** Dispatch 2-3 packets with alternative framings rather than agonizing alone.

## Dev loop (autonomous)

[coord/dev_loop/](coord/dev_loop/) is the prototype autonomous loop driving this project. Shared state in `state.json`. Four supervisors (creativity/developing/testing/integrating) per [supervisors/](coord/dev_loop/supervisors/). Manager logic in `manager.md`. Engine routing rules in `dispatch-rules.md`. Currently runs as in-session ScheduleWakeup ticks; will run via `bin/register-dev-loop-task.ps1` (Windows Task Scheduler) when operator activates persistent mode.

## Memory entries this session inherits

Load these from `~/.claude/projects/D--xaxiu-harness-standalone/memory/` (this project's isolated Claude memory) at session start:

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
