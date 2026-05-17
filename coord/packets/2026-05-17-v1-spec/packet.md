# Packet: xaxiu-harness v1 Architecture Spec

## Mission
Produce a single architecture document for `xaxiu-harness` v1 — a cross-project multi-engine LLM dispatch + monitoring tool. Output to `D:/Projects/xaxiu-harness/spec/v1-architecture.md`.

## Context
The operator currently runs `xaxiu-swarm dispatch` ad-hoc per project. Pain points: no auto-fallback on engine failure, manual engine selection per task, no cross-project monitoring, plus recurring rules that should be enforced by code not memory (DeepSeek v4-flash needs `--no-thinking` for patches; Kimi fails on multi-domain bundles; never echo env-var values; etc.). The harness is the successor to xaxiu-swarm, applicable to any project (not just warehouse). Treat warehouse as one adapter among many.

## Critical constraints
1. **Non-technical operator** — adapters MUST be declarative YAML, never Python. Operator cannot author code. Tools shipped TO operator must be no-code (YAML, forms, natural language).
2. **One-click Windows installer** — never `pip install` for operator. Bundle Python runtime, register Task Scheduler entries, ship a first-run wizard.
3. **No persistent daemon** — every long-running concern (observer cycles, status drift checks, audit dispatches, dashboard server) is a Windows Task Scheduler entry that invokes the harness CLI as a one-shot. CLI is just verbs; Task Scheduler is the runtime.
4. **Env-var reuse** — read existing `KIMI_API_KEY`/`DEEPSEEK_API_KEY`/`ANTHROPIC_API_KEY` from system env. NEVER echo values (use `[ -n "$VAR" ] && echo SET`, never `${VAR:+SET}`). Optional `XAXIU_HARNESS_*_API_KEY` overrides.
5. **Cross-project portability** — core is project-agnostic. Per-project adapters (YAML files) add project-specific routing, status backend, scheduled tasks. Core NEVER imports adapter code; adapters NEVER live in core. Warehouse-specific behavior lives in a separate `xaxiu-harness-warehouse` adapter package.

## Required output sections
The architecture doc MUST cover all 10 sections below in this order:

1. **Repo layout** — directory structure for `D:/Projects/xaxiu-harness/` (src, adapters/, spec/, coord/, tests/, installer/, dashboard/)
2. **Adapter YAML schema** — full schema for per-project config: `name`, `project_root`, `routing_rules` (if/then/reason), `status_tracking` (backend pluggable: csv/markdown/jira/linear), `observer` (enabled, cadence_minutes, daily_retro_time, flag_patterns), `scheduled_tasks` (cron, command, idempotent). Include a complete warehouse-adapter example with the existing observer + STATUS.csv config baked in.
3. **CLI command surface** — every `harness <verb>` with arg signatures: `dispatch`, `status`, `observer-tick`, `retro`, `install`, `init`, `env`, `dashboard-serve`, `loops`, `engines`, `priority`, `burst`, `lock`. Document exit codes.
4. **State file format** — `harness.config.yml` (global), `state/active_dispatches.json`, `state/loops.json`, `state/engine_health.json`. SQLite schema for `history.db` (dispatches, fallbacks, observer_cycles, status_writes).
5. **Dashboard data contracts** — FastAPI endpoints (REST + WebSocket), JSON shapes for engine pool / active dispatches / loops / event stream. WebSocket message types for live updates.
6. **Task Scheduler installer flow** — what `harness install` does on Windows: `schtasks /create` invocations for each scheduled concern. Idempotency rules (running twice is safe). Per-project task naming convention. Uninstall flow.
7. **Engine-specific guards** — DeepSeek v4-flash auto-`--no-thinking` for patches; Kimi multi-domain bundle splitter; anchor-fuzzy post-validator for FIND/REPLACE outputs; v4-flash packet-trap suppression boilerplate.
8. **Auto-fallback + log** — on engine failure or timeout, switch engines (never re-dispatch the same one); structured append to `state/engine_performance_log.jsonl` with fields: timestamp, project, packet_path, backend, model, outcome (success/timeout/api_error/packet_trap/...), latency_ms, fallback_to.
9. **Priority toggle + burst + lock** — per-engine HIGH/NORMAL/AVOID persistent state; time-bounded BURST override (route all → engine X for N min); LOCK state (exclusive routing, holds until cleared). Override hierarchy: lock > burst > per-project priority > global priority > auto-routing rules.
10. **Plugin interface** — Python ABCs for new engine backends (`Engine`) and new status backends (`StatusBackend`). Show the warehouse CSV backend + a generic Markdown backend as concrete examples.

## Output format
Single markdown doc. Target 200–400 lines. Use tables for schema fields, YAML code blocks for examples, ASCII for dashboard mocks. No prose padding. No "executive summary" — the structure IS the spec. Reader is a developer (Kimi or DeepSeek) who will dispatch implementation in subsequent packets against this contract.

## Reference materials
- xaxiu-swarm current usage: `xaxiu-swarm dispatch --backend <name> --model <model> --deliverable <path> <packet.md>`
- Engine routing rule: Kimi for non-V-file work + screenshots-out only; DeepSeek for V-file-spanning + math + ship-critical (DeepSeek v4 context = 1M tokens)
- Anchor-accuracy rule: DeepSeek normalizes quotes/indent in FIND blocks (1/3 byte-exact even with thinking on); Kimi reliable on single-site surgical patches but fails on multi-domain bundles
- Env-leak rule: `[ -n "$VAR" ] && echo SET` only, never `${VAR:+SET}${VAR:-MISSING}` (leaks values when set)
- Satisfactory-aesthetic UX north star: dashboard should feel like a sim/strategy game — dark steel base, amber/cyan accents, pipe/conveyor flow lines, mood-ring engine tiles, decision archaeology panels
