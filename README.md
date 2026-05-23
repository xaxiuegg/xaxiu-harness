# xaxiu-harness — cross-project multi-engine LLM dispatch + autonomous loop, v0.4.2

> One command center that sends work packets to Kimi K2.6, MiMo Pro v2.5, DeepSeek v4-flash, or Anthropic; tracks every task in a shared spreadsheet; and keeps running even while you sleep.

---

## What is this?

**xaxiu-harness** is a dispatch and tracking tool for running AI-powered development across multiple projects.

- It sends work "packets" to four AI engines (Kimi K2.6, MiMo Pro v2.5, DeepSeek v4-flash, Anthropic) and picks the best one for each job automatically.
- It keeps a living task list in [`coord/STATUS.csv`](coord/STATUS.csv) so you always know what is in progress, shipped, or blocked.
- It can run on its own through Windows Task Scheduler, checking health, cycling observers, and producing daily summaries without human intervention.
- It includes an autonomous orchestrator: drop a markdown spec into `spec/auto/` and `harness queue execute` plans + dispatches + validates it.

---

## What's new (Wave 5 closeout, 2026-05-23)

- **Kimi wiring fix (W5-V)** — Kimi K2.6 now reliably handles source-laden packets (was silently empty under wiring drift). Two bugs fixed: streaming requirement (`stream=true`) and non-standard SSE prefix (`data:` without space).
- **Unbounded `max_tokens` for subscription engines (W5-W)** — Kimi default raised 32K → 200K, MiMo 32K → 131K (hardware max). Operator directive: don't artificially cap engines on flat-rate subscriptions.
- **Autonomous orchestrator (Phase 3)** — `harness orchestrator start` (Path α: STATUS-backlog-driven) and `harness queue execute` (Path β: spec-queue-driven). Both ship and validated end-to-end.
- **Kimi-API default planner (W5-AA)** — `harness queue execute --planner-engine kimi-api` (new default) plans for $0 instead of using Claude.
- **Strict paths (W5-BB)** — declare `## Strict Paths` in a spec to bind the worker to exact output paths. Pre-creates dirs, injects packet hint, post-validates file existence.
- **L5 operator-escalation contract (W5-Y, W5-DD)** — `HarnessError` subclasses that reach the CLI top level emit a stable `*** OPERATOR ESCALATION (L5) ***` banner so observer scrapers can grep reliably.
- **Task Scheduler interval bounds (W5-Z)** — `orchestrator install-scheduler` now auto-selects `/SC MINUTE` vs `/SC DAILY` based on interval (fixes the `Invalid value for /MO` failure on intervals ≥ 24h).

See [`memory/engine-reliability.md`](memory/engine-reliability.md) for the post-W5 reliability matrix.

---

## Quick start

1. Clone the repo
   ```powershell
   git clone https://github.com/xaxiuegg/xaxiu-harness.git
   ```
2. Create a virtual environment and install
   ```powershell
   cd xaxiu-harness && python -m venv .venv && .venv\Scripts\activate && pip install -e .
   ```
3. Create your first project adapter
   ```powershell
   harness init -p my-first-project -t solo-dev
   ```

After step 3 you can dispatch your first packet:
```powershell
harness dispatch -p my-first-project --packet packet.md
```

For help on any command:
```powershell
harness <verb> --help
```

---

## The 25 CLI verb groups at a glance

| Group | Subcommands | What it does |
|---|---|---|
| `adapter` | `from-description`, `list`, `validate` | Create or check project adapters (YAML configs that tell harness how to talk to each project). |
| `budget` | `show`, `summary`, `set-cap`, `reset` | Track spending per engine and set monthly spending limits. |
| `burst` | — | Temporarily send all traffic to one engine for a set number of minutes. |
| `coord` | `plan`, `plan-from-description`, `run`, `work`, `retry`, `integrate`, `replan`, `status`, `watch`, `list`, `cancel`, `cleanup` | Run the multi-agent coordinator: plan a wave (from spec OR natural language), run workers, retry failed ones, merge results, live-tail events, list runs, cancel in-flight, GC stale worktrees. |
| `dashboard-serve` | — | Launch the operator web dashboard (default port 7878). |
| `dispatch` | — | Send a work packet to an engine; auto-routes if you do not pick one. |
| `engines` | `cooldowns` | List engines + active cooldown windows from state.json. |
| `env` | — | Show which API keys are set (Kimi, DeepSeek, Anthropic, MiMo). |
| `heartbeat` | `pulse`, `show` | Emit or view a "still alive" signal from the dev loop. |
| `init` | — | Create a starter adapter YAML for a new project. |
| `install` | — | First-run setup wizard (Task Scheduler entries and config). |
| `lock` | — | Lock an engine so the router cannot use it until you release it. |
| `loop` | `init`, `tick`, `start`, `stop`, `status` | Manage the autonomous dev loop that runs ticks on a schedule. |
| `loops` | — | Manage user-defined scheduled loops (advanced). |
| `memory` | `list`, `show` | Read the engine-agnostic operator memory (`memory/*.md`) that every worker packet sees. |
| `observer` | `init`, `arm`, `disarm`, `pause`, `resume`, `status`, `flags`, `ack`, `cycle-now`, `daily-retro`, `audit-chat`, `install-scheduler`, `uninstall-scheduler` | Independent audit and flagging system that watches for problems (now includes chat-transcript drift detection). |
| `orchestrator` | `start`, `install-scheduler` | **W5-T Path α** — autonomous orchestrator that picks next STATUS.csv TODO, composes a spec, runs it. Optionally arms Task Scheduler at any cadence (auto MINUTE/DAILY). |
| `priority` | — | Set how strongly the router prefers one engine over others. |
| `proxy` | `start`, `stop`, `status`, `reset-circuit`, `quarantine` | Start the stateful API proxy that balances 4 Kimi keys with circuit breaking. |
| `queue` | `list`, `execute` | **W5-U Path β** — burst-composition spec queue.  Drop `spec/auto/*.md` files, run `harness queue execute --once --planner-engine kimi-api --no-merge` to process them autonomously. |
| `replay` | — | Reconstruct what happened during a past dispatch for debugging. |
| `retro` | — | Generate a daily retro summary from history. |
| `session` | `check`, `bootstrap`, `ack`, `crisis-check`, `arm-crisis-check`, `ok-to-stop` | Monitor session health and recommend when to start a fresh Claude session; `ok-to-stop --json` exposes the canonical "are you done yet" gate. |
| `state` | `inspect` | Pretty-print the dev loop runtime state file for human reading (uses ConfigCorruption + L5 banner on bad JSON). |
| `status` | `report`, `init`, `add`, `update`, `list`, `summary`, `verify` | Manage the canonical task tracker ([`coord/STATUS.csv`](coord/STATUS.csv)). |

---

## The autonomous loop

The harness can run three Windows Task Scheduler entries so it keeps working without manual clicks:

| Entry | Cadence | Purpose |
|---|---|---|
| **LoopTick** | Every 30 minutes (configurable) | Runs one tick of the dev loop: check queues, dispatch work, update STATUS.csv. |
| **ObserverCycle** | Every 60 minutes (configurable) | Audits recent activity for anomalies and raises flags if something looks wrong. |
| **DailyRetro** | Once per day at 23:00 | Generates a summary of what shipped, what stalled, and what should happen next. |

Arm them with:
```powershell
harness loop start --cadence-minutes 30
harness observer install-scheduler --cadence-minutes 60 --daily-time 23:00
```

Stop them with:
```powershell
harness loop stop
harness observer uninstall-scheduler
```

---

## The session-handoff monitor

Long Claude sessions can slow down or crash as they grow. The session monitor watches the transcript size and recommends a handoff before trouble hits.

- Run `harness session check` to see the current health score.
- The recommendation levels are **SOFT** (informational), **STRONGLY** (consider switching soon), and **CRITICAL** (switch now or risk a crash).
- Thresholds are calibrated from 8 MB, 18 MB, and 35 MB transcript sizes, based on the operator's historic crash at 52 MB.
- If a handoff is recommended, `harness session bootstrap` writes a "master prompt" you can paste into a fresh Claude session to resume exactly where you left off.

---

## v2 architecture (planner / worker pattern)

The next-generation coordination layer is documented in [`spec/multi-agent-harness-architecture.md`](spec/multi-agent-harness-architecture.md). It is a 24-slot parallel coordinator that uses isolated git worktrees so multiple AI workers can edit code at the same time without stepping on each other. Work is handed off between stages via JSON files rather than long chat histories, which keeps context fresh and errors recoverable. v2 is fully implemented and validated end-to-end (Phase 3 Path β milestone, 2026-05-23).

### Strict-path specs

Operator-declared output paths bind the worker via a `## Strict Paths` section in the spec markdown:

```markdown
## Strict Paths
- coord/operator/engine-cheatsheet.md
- coord/operator/engine-cheatsheet-index.json
```

The planner extracts these and overrides any LLM emission of the field; the worker pre-creates parent dirs, injects a STRICT PATHS callout into the dispatch packet, and post-validates that each file exists in the worktree at exactly that path. Missing files fail the worker with `error_tag=L3.worker.E_STRICT_PATH_MISSING`. See [`spec/samples/strict-paths-demo.md`](spec/samples/strict-paths-demo.md) for a worked example.

### L5 operator-escalation banner

When any `HarnessError` subclass with `level >= 5` escapes a CLI verb, the top-level wrapper emits a stable banner:

```
*** OPERATOR ESCALATION (L5) ***
  tag:     L5.config.E_CONFIG_CORRUPTION
  domain:  config
  code:    E_CONFIG_CORRUPTION
  message: state.json is not valid JSON: ...
*** action: operator review required ***
```

Observer scrapers grep for the leading marker. L1–L4 errors emit a one-line `[Ln.domain.E_CODE] message` summary instead. See [`spec/errors.md`](spec/errors.md) for the full taxonomy.

---

## Project structure

```
xaxiu-harness/
├── src/harness/           # Core Python source (CLI, engines, state, loops, etc.)
│   ├── adapters/          # Project adapter schemas and loader
│   ├── budget.py          # Cost ledger
│   ├── cli.py             # 22-verb CLI
│   ├── coord/             # v2 planner / worker / coordinator
│   ├── dashboard/         # FastAPI + WebSocket operator UI
│   ├── engines/           # Engine ABC + 4 concrete backends
│   ├── errors.py          # L1-L5 error taxonomy
│   ├── heartbeat.py       # Liveness signal
│   ├── loops/             # Autonomous loop productization
│   ├── observer/          # Audit + flagging primitive
│   ├── operator/          # Operator config surface
│   ├── proxy/             # v2 stateful 4-key API proxy
│   ├── replay.py          # Decision archaeology
│   ├── secrets/           # DPAPI secrets storage
│   ├── session/           # Session-handoff monitor
│   ├── state/             # JSON + SQLite + JSONL state layer
│   └── status/            # STATUS.csv tracker primitive
├── spec/                  # Architecture and feature specs
├── coord/                 # Runtime state, STATUS.csv, dev_loop state
├── tests/                 # pytest suite
├── adapters/              # Your project adapter YAMLs (generated at runtime)
├── .harness/              # Runtime data: runs, worktrees, proxy state
├── pyproject.toml         # Package metadata and dependencies
└── README.md              # This file
```

---

## Memory + multi-session scoping

This repo is designed to live alongside other projects (for example, a warehouse project). Each project keeps its own adapter, its own STATUS.csv, and its own task history. The harness uses project scoping rules so work dispatched for one repo never leaks into another. If you work across multiple repos in the same day, each one stays isolated.

---

## License / contributing

MIT (see LICENSE).
