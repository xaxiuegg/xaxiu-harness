# CLAUDE.md — xaxiu-harness

You are working in the **xaxiu-harness** project. Cross-project multi-engine LLM dispatch + monitoring tool, successor to `xaxiu-swarm`. **This is NOT the warehouse project** — different session scope. Don't update warehouse's STATUS.csv; don't dispatch warehouse work. See `feedback_multi_session_scoping.md` in memory.

## Current state — v0.3.0 (2026-05-16)

| Component | Status | Files |
|---|---|---|
| Adapter schema (Pydantic v2 + validators) | Done | [src/harness/adapters/schema.py](src/harness/adapters/schema.py) |
| CLI (13 verbs, Click) | Done — all stubbed except `env` | [src/harness/cli.py](src/harness/cli.py) |
| Engine ABC + 3 concrete impls (DeepSeek/Kimi/Anthropic httpx) | Done | [src/harness/engines/base.py](src/harness/engines/base.py), [concrete.py](src/harness/engines/concrete.py) |
| Engine guards (packet-trap / kimi-empty / anthropic-refusal / anchor-fuzzy) | Done | [src/harness/engines/guards.py](src/harness/engines/guards.py) |
| Auto-fallback orchestrator | Done — LOCK>BURST>priority>rules | [src/harness/engines/dispatcher.py](src/harness/engines/dispatcher.py) |
| State layer (JSON + SQLite + closed-schema JSONL with redact) | Done | [src/harness/state/](src/harness/state/) |
| Adapter loader + path validation | Done | [src/harness/adapters/loader.py](src/harness/adapters/loader.py) |
| DPAPI secrets (Windows-only v0.x) | Done | [src/harness/secrets/dpapi.py](src/harness/secrets/dpapi.py) |
| Dashboard backend + frontend | **Pending Wave 3** | — |
| Windows installer + first-run wizard | **Pending Wave 4** | — |
| Templates + NL→YAML translator + visual config builder | **Pending Wave 5** | — |

Smoke test that everything imports: `PYTHONPATH=src python -c "from harness import cli; print(sorted(cli.cli.commands.keys()))"`

## Where to look

- **Architecture specs**: [spec/v1-architecture.md](spec/v1-architecture.md) (technical skeleton, 411L), [spec/v1.1-operator-experience.md](spec/v1.1-operator-experience.md) (operator UX, 479L), [spec/v1.2-security-amendments.md](spec/v1.2-security-amendments.md) (drop-in security spec text for 11 HIGH + 14 MED audit findings, 582L)
- **Accepted v0.x limitations**: [spec/ACCEPTED_LIMITATIONS.md](spec/ACCEPTED_LIMITATIONS.md) — 3 explicit gaps (chmod-on-Windows / rotation lock / broad-except) with resolution paths. Auditor protocol included.
- **Security audits**: [security/audits/](security/audits/) — 7 audit reports from agents 1-7, all clean or amended.
- **Dispatch packets**: [coord/packets/](coord/packets/) — every engine dispatch's packet preserved.

## Operator profile (load-bearing)

Operator is **non-technical**: can edit YAML/run commands/manage Task Scheduler, **cannot** author Python/shell from scratch. Tools shipped TO operator must be no-code (YAML, GUI, NL). See memory `user_non_technical_role.md`.

## Engine routing rules (per memory `feedback_engine_routing_2026_05_11.md`)

- **Kimi-first** for non-V-file tasks (subscription cost, surgical patches reliable)
- **DeepSeek** for V-file-spanning + math + structured code generation (1M context window, schema correctness)
- **Claude in-session only** — never as swarm worker
- Default DeepSeek model: `deepseek-v4-flash` (5× cheaper than v4-pro)
- Dispatch tool: `xaxiu-swarm dispatch --backend <name> --model <model> --deliverable <path> --context-file <ctx> <packet.md>` (note: this IS the predecessor tool — xaxiu-harness itself isn't installed yet)
- **Never echo env-var values** — `[ -n "$VAR" ] && echo SET`, never `${VAR:+SET}`

## Claude operating role (inherited from warehouse role)

Direct authorship limited to 7 classes: chat / spec docs / packet drafts / validation runs / merge ops / summaries / memory writes. Hard ceiling: 30 LOC code, 80 LOC doc per artifact. Everything else dispatches to Kimi (Python scaffolding) or DeepSeek (V-file or schema correctness).

## Wave 3 candidates (operator to pick)

1. Dashboard backend + frontend (FastAPI + WebSocket + Satisfactory-themed HTML/CSS/JS)
2. Templates + NL→YAML translator + visual config builder
3. Windows installer + first-run wizard

## Session discipline

- DeepSeek wraps outputs in ` ```python `/` ```markdown ` fences — strip before commit
- Every Wave landing → spawn security audit agent before commit
- All audit findings → fix inline OR document in `ACCEPTED_LIMITATIONS.md` with resolution path
- Use TodoWrite for multi-step work
- Don't touch warehouse files or STATUS.csv from this session
