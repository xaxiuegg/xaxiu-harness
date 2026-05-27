# xaxiu-harness — cross-project multi-engine LLM dispatch + autonomous loop, v0.1.0 (v1.0.0-rc.1 tagged)

> One command center that sends work packets to Kimi K2.6, MiMo Pro v2.5, DeepSeek v4-flash, Anthropic, or Gemini; tracks every task in a shared spreadsheet; and keeps running even while you sleep.

**Version note (2026-05-25)**: package version stays at `0.1.0` while the Horizon C internal-tool work continues; the current release tag is **`v1.0.0-rc.1`**.  Run `harness capabilities` for the live install snapshot — it's the canonical source of truth for what this binary can do.

**Handing this to someone else?** → **[docs/HANDOFF.md](docs/HANDOFF.md)** is the one-page sharing kit: the URL, the message, and the exact prompt to paste into their Claude Code.  Recipient time: 15-25 min.

**Using the harness from another project?** → [docs/USING_HARNESS_FROM_OTHER_PROJECTS.md](docs/USING_HARNESS_FROM_OTHER_PROJECTS.md) — once installed, the harness works from any directory; one command (`harness install-agent-instructions`) makes it discoverable to every Claude Code session on the machine.

**Visual operator manual?** → **[docs/HARNESS_VISUAL_MANUAL.md](docs/HARNESS_VISUAL_MANUAL.md)** is the screenshot-driven walkthrough — what each command looks like + when to reach for each.  Refined by a 3-engine review panel.

**Non-technical operator first-time setup?** → [docs/OPERATOR_QUICKSTART.md](docs/OPERATOR_QUICKSTART.md) is the 30-minute blank-machine-to-first-dispatch guide.

**Daily operations?** → [docs/INTERNAL_OPERATOR_RUNBOOK.md](docs/INTERNAL_OPERATOR_RUNBOOK.md) covers laptop-dies recovery, key rotation, engine-down debugging.

**Fresh agent?** → [docs/AGENT_QUICKSTART.md](docs/AGENT_QUICKSTART.md) gets you from `git clone` to a real engine response in under 5 commands, plus a hallucination-resistance checklist.

---

## What is this?

**xaxiu-harness** is a dispatch and tracking tool for running AI-powered development across multiple projects.

- It sends work "packets" to four AI engines (Kimi K2.6, MiMo Pro v2.5, DeepSeek v4-flash, Anthropic) and picks the best one for each job automatically.
- It keeps a living task list in [`coord/STATUS.csv`](coord/STATUS.csv) so you always know what is in progress, shipped, or blocked.
- It can run on its own through Windows Task Scheduler, checking health, cycling observers, and producing daily summaries without human intervention.
- It includes an autonomous orchestrator: drop a markdown spec into `spec/auto/` and `harness queue execute` plans + dispatches + validates it.

---

## What's new (Wave 13, 2026-05-25)

This section is updated by-hand and drifts; **`coord/STATUS.csv` is the canonical truth** and `harness today` shows the last 24h live.

- **`harness.review()` + `harness.capabilities()` SDK functions** — multi-engine document review is now programmatically callable, and `capabilities()` gives a one-call introspection dict (SDK fns, CLI verbs, engine key presence, lens-sets, audit ledger).  W13 Wed-Thu bundle.
- **W13 Tier 1 Shifts A + F (auto-defaults)** — `harness review` auto-picks `--lens-set` from file extension (`.py` → code-review, `.md`/`.pdf` → doc-review, else default) and `--max-tokens` to a safe floor of 4000 (or 1000 with `--quick`).  Explicit flags always win.
- **W13-AUDIT-JSONL forensic ledger** — every `harness.dispatch()` call lands one redacted row in `~/.harness/audit.jsonl` (7 secret-pattern classes scrubbed; never raises; size-cap + age-prune).  Surfaced via `harness audit show` / `harness audit summary`.
- **W13-INSTALL-VERIFY CI gate** — every PR runs `pip install -e .` in a fresh venv and verifies the console script + SDK imports + `harness review --help` all work end-to-end.  Closes the "fresh-clone agent install promise" gap from AGENT_QUICKSTART.md.
- **W13-ENGINE-RETRY-RESILIENT** — all 5 engine adapters (Kimi, DeepSeek, MiMo, Anthropic, Gemini) share a retry helper that classifies transient errors (`RemoteProtocolError`, `TimeoutException`) and retries once with a 0.5s cooldown.  Replaces the opaque `error="internal"` strings with descriptive `repr(exc)`.
- **W13-FUTURE-MARKER-AUDIT** — docs that reference unimplemented CLI verbs now must use the `**FUTURE (...)**` marker, enforced by `tests/test_docs_no_future_as_present.py`.  Same gate now also enforces (via the new `tests/test_docs_mention_all_sdk_fns.py`) that every public SDK name appears in `docs/AGENT_QUICKSTART.md`.

See [`memory/engine-reliability.md`](memory/engine-reliability.md) for engine reliability + cooldown policy and [`docs/INTERNAL_OPERATOR_RUNBOOK.md`](docs/INTERNAL_OPERATOR_RUNBOOK.md) for operational procedures.

---

## Quick start (fresh machine)

**Non-technical operator?** Start with [`docs/OPERATOR_QUICKSTART.md`](docs/OPERATOR_QUICKSTART.md) instead — guided 30-minute walkthrough from blank machine to first dispatch.

For everyone else:

1. Clone the repo
   ```powershell
   git clone https://github.com/xaxiuegg/xaxiu-harness.git
   ```
2. Create a virtual environment and install
   ```powershell
   cd xaxiu-harness && python -m venv .venv && .venv\Scripts\activate && pip install -e .
   ```
3. Set provider API keys (easiest path: the keys UI)
   ```powershell
   python -m harness keys serve
   ```
   Opens a browser form at `127.0.0.1:<port>` for pasting + testing keys.  Or copy `.env.example` to `.env` and edit by hand.  See [`.env.example`](.env.example) for the full env-var list.
4. Verify your install + key wiring
   ```powershell
   harness doctor
   ```
   Six-check traffic-light report; tells you exactly what to fix if anything's red.

After step 4 you can:

- **Ask a cross-engine panel** — single command, 3 engines in parallel:
  ```powershell
  harness ask "should we deprecate the legacy swarm/kimi-api?"
  ```
- **Dispatch a single packet** — for older multi-project workflows:
  ```powershell
  harness init -p my-first-project -t solo-dev
  harness dispatch -p my-first-project --packet packet.md
  ```
- **See all 50+ verbs** — `harness --help` (live) or `harness capabilities` (introspected snapshot).

## Optional second repo: `xaxiu-swarm`

xaxiu-harness's Pattern B engines (`*-via-claude`) work entirely from this repo + the `claude` CLI binary.  If you want the **agentic swarm path** (`swarm/kimi`, `swarm/claude-mimo`, `swarm/deepseek` etc. — multi-file edits, multi-turn tool use), clone the sibling repo:

```powershell
git clone https://github.com/xaxiuegg/xaxiu-swarm.git
cd xaxiu-swarm && pip install -e .
# Or via uv tool:
uv tool install --from . xaxiu-swarm
```

Verify with `xaxiu-swarm backends`.  Without this second clone, you can still use everything in this repo's CLI; the `swarm/*` backends just won't be available.

---

## The CLI verb groups at a glance

> **Note**: this table drifts.  Run `harness --help` for the live list or `harness capabilities` for the introspected snapshot.  As of v1.0.0-rc.1 (2026-05-25) there are 50+ top-level verbs.

| Group | Subcommands | What it does |
|---|---|---|
| `adapter` | `from-description`, `list`, `validate` | Create or check project adapters (YAML configs that tell harness how to talk to each project). |
| `audit` | `show`, `summary` | **W13-AUDIT-JSONL**: read the forensic ledger at `~/.harness/audit.jsonl`.  Every `harness.dispatch()` lands one redacted row. |
| `backup` | `create`, `list`, `prune`, `restore` | **W13-BACKUP-RESTORE**: snapshot `.harness/`, `coord/observer/`, `coord/STATUS.csv`, `state/` for laptop-dies recovery.  Secrets stay out by design. |
| `budget` | `show`, `summary`, `set-cap`, `reset` | Track spending per engine and set monthly spending limits. |
| `capabilities` | — | **W13 Wed-Thu**: introspection only — print SDK functions, CLI verbs, engine key presence, lens-sets, audit ledger.  Cheap; no engine dispatch. |
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
| `review` | — | **W12-B + W13 Wed-Thu**: drop a TXT/MD/PDF/source file for parallel multi-engine review.  Auto-picks lens-set from extension; `--quick` for fast preview. |
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
