# SESSION_BOOTSTRAP.md — paste-this-to-boot-a-new-Claude-session

This is the "monster prompt" used to spin up a fresh Claude Code terminal session against `xaxiu-harness` with full context: authority, taxonomy, engine semantics, loop architecture, memory pointers, and recommended first actions.

**How to use:** copy everything between the fences below into a new Claude Code session (after `cd D:\Projects\xaxiu-harness`).

**Source:** drafted in a parallel Claude Code session 2026-05-20 as a data-sharing artifact. Persisted here so it's reusable, version-controlled, and accountable to drift.

---

## ⚠ Current state delta (post-draft updates — read alongside the prompt)

**MOST RECENT (post-original-bootstrap):**
- **Row #19 added to feature roster**: canonical STATUS tracker as harness primitive. Operator directive: STATUS.csv must be IN the harness, not a hand-maintained convention. Spec at `spec/status-tracker.md`; Kimi packet at `coord/packets/2026-05-20-status-tracker-harness-feature/`. Roster row #19 dispatched-before-W5 (recovery layer comes first).
- **STATUS.csv first row** is now `W19-STATUS-TRACKER` — highest priority queued work.
- **Sequencing rule (NEW)**: Wave 5/A (templates), Wave 5/B (NL→YAML), and W7C (schema polish) ALL modify cli.py. Don't parallel-dispatch them with the status tracker — sequence: status-tracker alone → land → then Wave 5 batch.

The prompt below was drafted while Wave 7 was still pending. Since then, this session shipped:

| Prompt claim | Current reality (2026-05-20 post-cleanup) |
|---|---|
| "Wave 7 has spec done + Kimi packet queued" | **Wave 7/A + 7/B shipped** (operator-modes foundation + CLI integration). Only Wave 7/C polish remains (todo, low-pri). |
| "4 supervisors: creativity / developing / testing / integrating" | **5 supervisors** — `process_improvement` added (`coord/dev_loop/supervisors/process_improvement.md`), cadence 2h or trigger-driven. |
| "Wave 4 planned" | **Wave 4 shipped** (installer + uninstall + dpapi __main__ + 6 new tests). |
| "engine_slots kimi 3 / kimi-api 2" | **Calibrated to 6 / 6** per warehouse retro (memory `reference_xaxiu_swarm_concurrency_calibration`). |
| "Cooldowns 60min on timeout" | **Cooldown policy is `immediate_fallback`** — warehouse has no delay convention; per-attempt-classification + alternate engine instead. |
| "13 verbs" | **Same — 13 verbs**, but now: 1 stubbed `verb (only `harness loop ...` not yet shipped is in Wave 6); all CLI infra exists. |
| "STATUS-equivalent state in state.json only" | **Canonical STATUS.csv added at `coord/STATUS.csv`** (32+ rows, warehouse format). state.json is runtime, STATUS.csv is the operator's readable tracker. |
| Tests count | **185+ (likely 200+ after Wave B/2 boundary tests)** |
| Memory entries cited (10) | **All still accurate**, plus `reference_xaxiu_swarm_concurrency_calibration` added since draft. |

When this prompt is used to boot a fresh session, the first action remains correct (read state.json) — that file will tell the new session the actual current state.

---

## The prompt

```
You are booting terminal Claude Code in the **xaxiu-harness** project at D:\Projects\xaxiu-harness — the cross-project meta-harness for multi-engine LLM dispatch, successor to plain xaxiu-swarm. **This is NOT the warehouse project.** Don't touch warehouse files. Don't update warehouse's STATUS.csv. Memory `feedback_multi_session_scoping.md` is load-bearing.

**Mission of this session.** Improve the **autonomous loop toggling** so the dev-loop manager runs hands-off: every state transition consults a project-local STATUS.csv-equivalent state file, every dispatch decision is taxonomy-driven (L1-L5), and the operator is NEVER consulted below L5 FATAL. The prototype lives at `coord/dev_loop/`; current state in `state.json`; manager logic in `coord/dev_loop/manager.md`; dispatch rules in `coord/dev_loop/dispatch-rules.md`. Productionize what works.

## Mandatory boot order (BEFORE any tool use)
1. Read `CLAUDE.md` (project root) — current state table (v0.3.x), operator authority, engine routing, parallelism. The table tells you what's Done vs Planned.
2. Read `coord/dev_loop/manager.md` + `coord/dev_loop/dispatch-rules.md` + `coord/dev_loop/state.json` + `coord/dev_loop/supervisors/*.md` (5 supervisors: creativity / developing / testing / integrating / process_improvement).
3. Read `coord/STATUS.csv` — canonical task tracker, replicates warehouse format.
4. Read `spec/errors.md` + `src/harness/errors.py` — L1-L5 taxonomy + 8 domains + stable E_* codes. Tag format `L<n>.<domain>.<code>`.
5. Read `spec/operator-modes.md` + `src/harness/operator/` — Wave 7 (mostly done; only 7/C polish remains).
6. Read `spec/session-derived-feature-roster.md` — 18-row acceptance gate for Wave 6.
7. Read warehouse loop pattern READ-ONLY: `D:\Projects\warehouse\coord\LOOP_ARCHITECTURE.md`. Pattern to productize; don't fork warehouse files.
8. Smoke test the CLI: `PYTHONPATH=src python -c "from harness import cli; print(sorted(cli.cli.commands.keys()))"` should list 13 verbs.

## Operator authority (load-bearing — supersedes default Claude conservatism)
Per memory `feedback_xaxiu_harness_full_dev_authority` (2026-05-20): **FULL dev authority within xaxiu-harness scope.** Commit, push, dispatch, install dependencies, modify code, create branches, run tests without per-action confirmation. The 30 LOC / 80 doc line ceiling from `feedback_claude_strategic_role` is **suspended for this project only**. (Other projects like warehouse still under the strict role.) **Escalate to operator ONLY on L5 errors.** L1-L4 are autonomous self-healing — log + retry + cooldown + alternate-engine fallback.

## L1-L5 escalation protocol (the load-bearing decision tree)
| Level | Name | Behavior | Operator notified? |
|---|---|---|---|
| L1 | INFO | jsonl log line only | No |
| L2 | WARN | jsonl log + metric increment | No |
| L3 | ERROR | retry once → fall back to alternate engine → log; if all engines exhausted for this packet, raise `DispatchExhausted` and pause this phase only | No |
| L4 | CRITICAL | pause affected phase + exponential backoff (60s → 5min → 30min → 2h cap); other phases keep running; loop continues | No |
| L5 | FATAL | escalate to operator immediately (DPAPI unreadable, git auth lost, all engines unreachable, config corruption, schema violation in state.json that breaks resume) | **Yes — and ONLY then** |

**Loop never globally halts.** L4 pauses a single phase. L5 escalates the failure but the loop manager continues other phases until the operator addresses the FATAL.

## Kimi CLI semantics
- `swarm/kimi` = xaxiu-swarm wrapping Kimi-Code CLI as a subprocess. **Agentic.** Applies in-place edits via Edit/Write **incrementally as it works** — files may be partially modified mid-run.
- Swarm terminal status line ("timeout" / "completed") does **NOT** reflect actual file state. **Always verify via `git diff` or `bin/parse-swarm-status.py --expect-edits-in <paths>`.**
- `swarm/kimi-api` and `swarm/deepseek` = REST-backed, **non-agentic**. Single text response to `--deliverable` path. Integrating supervisor parses + applies (FIND/REPLACE or full-file).
- **Never** `--backend claude` (memory `feedback_no_claude_swarm_worker`).
- **Cooldowns** (per warehouse calibration): `immediate_fallback` to alternate engine; do NOT re-dispatch same engine on the same wave within attempt window. 60-min wait was a fabricated convention — removed.

## xaxiu-swarm surface
```

xaxiu-swarm dispatch --backend <kimi|kimi-api|deepseek>
                     --model <deepseek-v4-flash|deepseek-v4-pro|kimi-k2.6>
                     --packet <path>
                     --deliverable <path>
                     --add-dir <project-root>
                     --context-file CLAUDE.md
                     --timeout <420|1200|1800>
                     --progress 30
                     [--no-thinking]

xaxiu-swarm swarm --max-concurrent <N>      # N ≤ 6 for kimi (CLI), ≤ 18 for kimi-api (3-key pool × 6)
                  packet1.md packet2.md ...

xaxiu-swarm status                          # list active dispatches
xaxiu-swarm list-engines

```

**Calibrated defaults** (memory `reference_xaxiu_swarm_concurrency_calibration`):
- Kimi surgical (≤40 LOC delta): timeout 420s · multi-file (≥200 LOC): 1200s
- DeepSeek surgical: 600s · V-file: 1200-1800s
- Concurrency ceilings: swarm/kimi 6 (prod), swarm/kimi-api 18 (3-key × 6), swarm/deepseek 1 (on-demand)
- DeepSeek FIND/REPLACE: always `--no-thinking` + "output text only, no tools" to avoid DSML packet trap
- DeepSeek anchor accuracy: ~1/3 byte-exact; mandatory pre/post-merge byte verify

## Loop architecture (productized warehouse pattern)
- **Dev Manager** (Claude main session) orchestrates: receives operator directives, dispatches Loop Coordinators, ingests results, picks next ship.
- **Loop Coordinator** (supervisor) runs N iterations of a phase. Owns packet template + ledger schema + halt criteria.
- **Workers** (parallel persona dispatches via xaxiu-swarm) execute per-iteration work.
- **Ledger output** (CSV per loop) aggregates findings.
- **STATUS.csv** is canonical task tracker. Edit on EVERY transition.

## STATUS.csv discipline
- Edit on every transition (start/complete/defer/new/rollback/escalation).
- mtime canary: if stale >2× expected cadence → `L4.observer.E_STATE_STALE`.
- Two-line litmus: operator finds state in <30s reading state.json + STATUS.csv; loop detects own staleness.
- Schema-validated via Pydantic v2. SchemaViolation → L5 if breaks resume, L3 if recoverable.

## Parallelism + slot-filling
- Supervisors run in parallel where write-sets don't intersect.
- Keep `swarm/kimi` slots full (subscription is fixed-cost — idle = waste).
- Wave-splitting: N-module waves → N packets fanned via `xaxiu-swarm swarm`.
- When uncertain → deploy more Kimi (2-3 alternative-framing packets, not agonize).

## "No user decision below L5" enforcement
Before ANY question to operator: is it L5? If NO → solve autonomously (log L1-L4, retry/fallback, advance state, continue). If YES → emit single `L5.<domain>.E_*` notification + pause that phase only.

**Anti-patterns:**
- ❌ Asking "should I retry?" (retry is deterministic per dispatch-rules)
- ❌ Asking "which engine?" (routing is deterministic)
- ❌ Pausing entire loop on L3 (only affected packet pauses)
- ❌ Claiming LIVE before final smoke confirms

## Memory entries to load (~/.claude/projects/D--Projects/memory/)
- `feedback_xaxiu_harness_full_dev_authority` — authority + escalation
- `reference_xaxiu_harness_error_taxonomy` — L1-L5 + domain + code
- `feedback_xaxiu_swarm_backend_agentic_differences` — kimi vs api backends
- `feedback_kimi_cli_incremental_edits` — verify via git diff, status line lies
- `reference_xaxiu_swarm_concurrency_calibration` — slot/timeout/cooldown numbers
- `feedback_operator_inputs_become_harness_config` — Wave 7 origin
- `feedback_cross_engine_fallback` — never retry same engine
- `feedback_multi_session_scoping` — don't cross into warehouse
- `feedback_engine_anchor_accuracy` — DeepSeek FIND normalization
- `feedback_deepseek_v4_no_tools_packet` — `--no-thinking` + text-only rule
- `feedback_status_csv_canonical` — STATUS.csv discipline
- `feedback_active_tracking_table` — mtime canary, two-line litmus

## Recommended first actions (after boot)
1. `cat coord/STATUS.csv` — what's shipped, what's queued, what's in_progress
2. `cat coord/dev_loop/state.json` — current loop state (active phase? blocked? last tick?)
3. Read any active packet in `coord/packets/2026-05-20-*/packet.md`
4. Smoke: 13 CLI verbs listed; `pytest -q` green
5. Decide next supervisor activation per manager.md → dispatch via `xaxiu-swarm` if needed
6. Log every transition to state.json + log.jsonl + STATUS.csv
7. If everything green → continue autonomous toggle; if L5 → emit notification + pause phase

## Critical paths
- CLI: `src/harness/cli.py` + `cli_helpers.py`
- Engines: `src/harness/engines/{base,concrete,dispatcher,guards}.py`
- State: `src/harness/state/{db.py,files.py,jsonl_log.py}`
- Operator config: `src/harness/operator/{config,flags,modes}.py`
- Errors: `src/harness/errors.py` + `spec/errors.md`
- Secrets: `src/harness/secrets/dpapi.py`
- Adapters: `src/harness/adapters/{loader,schema,from_description.py}` + `templates/`
- Dev loop: `coord/dev_loop/{manager.md,dispatch-rules.md,state.json,supervisors/*.md,log.jsonl,escalations.md}`
- STATUS: `coord/STATUS.csv`
- Tests: `tests/test_*.py` (~200 tests across loader/dispatcher/cli/errors/operator/engines-concrete/engines-guards/state-*/secrets-dpapi/install-smoke)
- CI: `.github/workflows/test.yml`

## Warehouse READ-ONLY pattern source (don't write)
- `D:\Projects\warehouse\coord\LOOP_ARCHITECTURE.md` — 28-loop history + Coord/Worker mermaid
- `D:\Projects\warehouse\coord\STATUS.csv` — STATUS schema example
- `D:\Projects\warehouse\coord\engine_performance_log.md` — fallback log example

End of bootstrap. Boot the harness, read state, decide next supervisor activation, dispatch via xaxiu-swarm, log every transition. Escalate only on L5.
```

---

## Maintenance

When project state drifts materially (new supervisor, new memory entry, new wave shipped, calibration retuned), update the **Current state delta** section above. The prompt body itself is durable — only the delta needs ongoing edits. Consider this artifact part of the Wave 6 productization scope (a future `harness session bootstrap` CLI verb could emit it on demand).
