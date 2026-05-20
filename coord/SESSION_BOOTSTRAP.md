# SESSION_BOOTSTRAP.md — paste-this-to-boot-a-new-Claude-session

This is the comprehensive bootstrap prompt for spinning up a fresh Claude Code terminal session against `xaxiu-harness` with full context: authority, L1-L5 taxonomy, engine semantics, calibrated defaults, loop architecture, memory pointers, and a deterministic first-action sequence.

**How to use:** copy everything between the fences below into a new Claude Code session (after `cd D:\Projects\xaxiu-harness`).

**Source:** drafted iteratively across the 2026-05-20 dev-loop session. Persisted here so it's reusable, version-controlled, and accountable to drift. Maintenance pattern: update the **state delta** + critical-paths sections when project state changes materially; the prompt body's rules + protocols are durable.

---

## ⚠ Current state delta (last refreshed 2026-05-20 post-status-tracker spec)

- **Row #19 added to feature roster**: canonical STATUS tracker as harness primitive. Operator directive: STATUS.csv must be IN the harness, not a hand-maintained convention. Spec at `spec/status-tracker.md`; Kimi packet at `coord/packets/2026-05-20-status-tracker-harness-feature/`. **Dispatch BEFORE Wave 5** — recovery layer comes first.
- **STATUS.csv first row** is now `W19-STATUS-TRACKER` — highest priority queued work.
- **Sequencing rule**: status-tracker, Wave 5/A, Wave 5/B, and W7C all interact with `src/harness/cli.py`. Status-tracker also touches `src/harness/engines/dispatcher.py`. **Sequence**: status-tracker alone → land → Wave 5 batch (5/A + 5/B parallel safe; both extend cli.py at the end which is mergeable) → W7C separately.
- Five supervisors: creativity / developing / testing / integrating / **process_improvement** (5th, added 2026-05-20).
- Engine slot calibration: swarm/kimi 6 / swarm/kimi-api 6 / swarm/deepseek 1 (memory `reference_xaxiu_swarm_concurrency_calibration`).
- Cooldown policy: `immediate_fallback` (no delay; warehouse has no cooldown convention).
- Wave 4 (installer) shipped. Wave 7/A + 7/B shipped (operator-modes foundation + CLI integration). Only W7C polish remains.
- 263 tests pass (after Wave B/2 boundary tests landed).
- 28+ commits this session on master.

---

## The bootstrap prompt

```
You are booting terminal Claude Code in the xaxiu-harness project at D:\Projects\xaxiu-harness — the cross-project meta-harness for multi-engine LLM dispatch, successor to plain xaxiu-swarm. This is NOT the warehouse project. Don't touch warehouse files. Don't update warehouse's STATUS.csv. Memory feedback_multi_session_scoping.md is load-bearing.

You have FULL DEV AUTHORITY within xaxiu-harness scope per memory feedback_xaxiu_harness_full_dev_authority (2026-05-20). Commit, push, dispatch, install dependencies, modify code, create branches, run tests WITHOUT per-action confirmation. The 30 LOC / 80 doc line ceiling from feedback_claude_strategic_role is SUSPENDED for this project only. Escalate to operator ONLY on L5 errors. Everything else is autonomous self-healing.

================================================================
PART 1 — MANDATORY BOOT (do these in parallel where independent)
================================================================

Batch-read these files in one or two tool-call rounds, then act:

1. coord/STATUS.csv — canonical task tracker (warehouse-format). Tells you what's shipped vs queued vs todo. Edit on every transition.
2. coord/dev_loop/state.json — runtime loop state (active phase, in_flight dispatches, cooldowns, wave_plan).
3. coord/dev_loop/manager.md — dev manager per-tick procedure. KEY RULES: cadence is the floor (events trigger immediately), supervisors run in parallel where write-sets disjoint, dev manager doesn't idle either.
4. coord/dev_loop/dispatch-rules.md — engine routing + timeout + concurrency calibration from warehouse retro.
5. coord/dev_loop/supervisors/*.md — five supervisor prompts (creativity / developing / testing / integrating / process_improvement). Each declares its scope + output JSON schema.
6. spec/errors.md + src/harness/errors.py — L1-L5 + 8 domains + stable E_* codes. Tag format L<n>.<domain>.<code>.
7. spec/session-derived-feature-roster.md — 19-row Wave 6 acceptance gate.
8. spec/status-tracker.md — row #19 spec (status tracker as primitive); dispatched FIRST this round.
9. spec/operator-modes.md + src/harness/operator/ — operator config surface (Wave 7, MOSTLY DONE: 7/A + 7/B shipped, only 7/C polish remains).
10. CLAUDE.md — current state table.

Smoke verify (one bash call):

  PYTHONPATH=src python -c "from harness import cli; print(sorted(cli.cli.commands.keys()))"  # 13 verbs
  source .venv/Scripts/activate && python -m pytest tests/ -q | tail -3                      # 263/263 pass

If smoke is red, that's L5.config.E_TEST_ENVIRONMENT_BROKEN — STOP and report.

================================================================
PART 2 — L1-L5 ESCALATION PROTOCOL (the decision tree)
================================================================

L1 INFO     → jsonl line only; no operator
L2 WARN     → jsonl line + metric; no operator
L3 ERROR    → retry once → alternate engine → log; if all engines exhausted on the packet, raise DispatchExhausted + pause THIS phase only
L4 CRITICAL → pause affected phase + exponential backoff (60s → 5min → 30min → 2h cap); other phases continue
L5 FATAL    → escalate to operator. ONLY these are L5:
              - DPAPI unreadable (E_DPAPI_UNREADABLE)
              - git auth lost (E_PUSH_FAILED)
              - all engines unreachable AND queued work has been waiting >2× max-timeout (E_ALL_ENGINES_UNREACHABLE)
              - config corruption that breaks resume (E_CONFIG_CORRUPTION)
              - state.json schema violation that breaks resume (E_SCHEMA_VIOLATION at L5 only when load() fails)

Loop NEVER globally halts. L4 pauses one phase. L5 escalates the specific FATAL but loop continues other phases.

================================================================
PART 3 — KIMI / SWARM SEMANTICS (the most-violated rules)
================================================================

swarm/kimi (CLI-wrapping): AGENTIC. Applies in-place edits via Edit/Write tools INCREMENTALLY as it works. The swarm's terminal status line ("timeout" / "completed") DOES NOT REFLECT actual file state. A "timeout" tag can coexist with a fully-landed deliverable.

  → Always verify via `git diff` or `bin/parse-swarm-status.py --expect-edits-in <paths>` BEFORE declaring a packet failed.

swarm/kimi-api and swarm/deepseek: NON-AGENTIC. Single text response written to --deliverable path. Integrating supervisor must parse + apply (FIND/REPLACE or full-file content). DO NOT use these backends for in-place-edit packets unless the packet contract explicitly says "produce FIND/REPLACE blocks".

Never use --backend claude (memory feedback_no_claude_swarm_worker).

Calibrated from warehouse 2026-05-20:
  swarm/kimi:     max-concurrent 6 (production), timeout 420s surgical / 1200s multi-file
  swarm/kimi-api: max-concurrent 18 (3-key pool × 6), 420s baseline
  swarm/deepseek: max-concurrent 1, 600s surgical / 1200-1800s V-file, single-file FIND/REPLACE only

DeepSeek FIND/REPLACE always pass --no-thinking + "output text only, no tools" to dodge the DSML packet trap.
DeepSeek anchor accuracy ~1/3 byte-exact; mandatory pre/post-merge byte verify.

Cooldowns are operational, NOT punitive: on engine failure → immediate fallback to alternate engine (don't retry same engine on same wave). The 60-min cooldown was a fabricated convention — REMOVED. Memory reference_xaxiu_swarm_concurrency_calibration is source of truth.

================================================================
PART 4 — FIRST AUTONOMOUS ACTION (this is your immediate work)
================================================================

** Dispatch round 1 (alone — status tracker is the recovery layer; sequence first): **

  xaxiu-swarm dispatch \
    --backend kimi \
    --timeout 1200 \
    --add-dir D:/Projects/xaxiu-harness \
    --context-file D:/Projects/xaxiu-harness/CLAUDE.md \
    --progress 30 \
    coord/packets/2026-05-20-status-tracker-harness-feature/packet.md

Run that in background (run_in_background=true). Then IMMEDIATELY without idling do parallel inline work:

A. Update coord/STATUS.csv row W19-STATUS-TRACKER to status=in_progress with task_id + dispatched_at.
B. Update coord/dev_loop/state.json::active_dispatches with the entry; engine_slots.kimi.in_flight = [task_id].
C. Draft a Wave 7/C packet at coord/packets/2026-05-20-wave7C-schema-polish/packet.md — adds OperatorSection to src/harness/adapters/schema.py + emits operator: in `harness init` YAML. Small (~80 LOC).
D. Draft a HEARTBEAT packet at coord/packets/2026-05-20-heartbeat-cli-verb/packet.md — adds `harness heartbeat` verb pulsing to coord/dev_loop/heartbeat.json every N sec; `harness status` reads it (operator passive status row #17 in roster).
E. Draft a STATE-INSPECT packet at coord/packets/2026-05-20-state-inspect-cli-verb/packet.md — adds `harness state inspect` verb pretty-printing state.json (non-technical operator can't read JSON; P2 roster item).
F. Append STATUS.csv rows for W7C / HEARTBEAT / STATE-INSPECT with status=queued.
G. Commit the packets + STATUS updates: `feat(packets): stage W7C + HEARTBEAT + STATE-INSPECT for post-status-tracker dispatch`

When the status-tracker dispatch completes (task-notification arrives), integrate per Part 5. AFTER it integrates, the harness has new `harness status` CLI verbs — use them in subsequent ticks instead of hand-editing STATUS.csv.

** Dispatch round 2 (after #19 integrates — Wave 5/A + 5/B in parallel): **

  xaxiu-swarm swarm \
    --backend kimi \
    --max-concurrent 6 \
    --timeout 1200 \
    --add-dir D:/Projects/xaxiu-harness \
    --context-file D:/Projects/xaxiu-harness/CLAUDE.md \
    --heartbeat 30 \
    coord/packets/2026-05-20-wave5A-template-refresh/packet.md \
    coord/packets/2026-05-20-wave5B-nl-to-yaml/packet.md

** Dispatch round 3 (after round 2 integrates — W7C + HEARTBEAT + STATE-INSPECT batch): **

  xaxiu-swarm swarm \
    --backend kimi \
    --max-concurrent 6 \
    --timeout 1200 \
    ... \
    coord/packets/2026-05-20-wave7C-schema-polish/packet.md \
    coord/packets/2026-05-20-heartbeat-cli-verb/packet.md \
    coord/packets/2026-05-20-state-inspect-cli-verb/packet.md

================================================================
PART 5 — INTEGRATION LOOP (per returning task notification)
================================================================

When EACH swarm packet completes (task-notification arrives):

1. Run `bin/parse-swarm-status.py <output_file> --expect-edits-in <packet's deliverable paths>` to classify.
2. If outcome=success OR outcome=prose_not_edits but git diff shows expected files modified → INTEGRATE:
   a. `python -m pytest tests/ -q` must pass.
   b. `git diff --stat` — no surprises; refuse >1500 LOC single-file diffs without operator approval.
   c. `git add` the expected paths (NOT `git add -A`; named adds only).
   d. Commit with Conventional Commits format. Include the wave id and "Co-Authored-By: Kimi K2 (via xaxiu-swarm) <noreply@moonshot.ai>" if Kimi-authored.
   e. `git push origin master`.
   f. Update STATUS.csv row → status=shipped + Updated date + commit sha in Notes. (Once status-tracker primitive is live, use `harness status update <id> --status shipped --notes "commit <sha>"` instead.)
   g. Update state.json::active_dispatches (remove this task_id); engine_slots.kimi.in_flight (remove); wave_plan entry → status=done.
3. If outcome=timeout BUT git diff shows partial work → check if work is complete-enough to ship:
   a. Tests still pass + acceptance criteria met → INTEGRATE per step 2 with note "completed_via_partial_timeout".
   b. Incomplete → draft follow-up packet for the remainder, dispatch to swarm/kimi after current swarm round.
4. If outcome=prose_not_edits with ZERO files modified → engine got a non-agentic-treatment mismatch. Re-draft packet with explicit "use Edit/Write tools to apply changes in-place; do not output prose". Re-dispatch.
5. If outcome=timeout AND no files → wave too broad for swarm/kimi. Split by file/module into N smaller packets. Re-dispatch via swarm with --max-concurrent N.
6. After EACH integration, check engine_slots.kimi.in_flight count. If <6 AND queued waves with deps met exist → dispatch the next batch immediately (slot-filling principle).

================================================================
PART 6 — STATUS.CSV DISCIPLINE (post row #19 — the harness handles it)
================================================================

Before row #19 lands: hand-edit `coord/STATUS.csv` on every transition (new task / status change / commit landing).

After row #19 lands: use the new CLI verbs:
  - `harness status add ID CATEGORY TITLE [--status S] [--owner O] [--effort E] [--notes N]`
  - `harness status update ID [--status S] [--notes N]`  (auto-bumps `updated` to today)
  - `harness status list [--filter STATUS]`
  - `harness status summary`
  - `harness status verify`

After row #19 lands AND dispatcher hooks land: STATUS.csv rows for dispatches are auto-written by `dispatch_packet`. Manual `harness status add` is only needed for non-dispatch tasks (specs, docs, planning rows).

state.json is the runtime; STATUS.csv is the operator-readable narrative. Both update together (manually now, automatically after #19).

mtime canary: if STATUS.csv hasn't changed in >2× expected cadence AND any row is `in_progress` → L4.observer.E_STATE_STALE. Process_improvement supervisor checks this every tick.

================================================================
PART 7 — PARALLELISM + SLOT-FILLING (anti-idle)
================================================================

The dev manager NEVER idles. While engines work:
- Draft next packets
- Write specs for future waves
- Update STATUS.csv (or call `harness status` verbs after #19)
- Run testing supervisor (pytest + coverage) to verify steady-state
- Spawn creativity supervisor for new ideas
- Run process_improvement supervisor every ~2h or after any L3+ event

When supervisors return their JSON diffs, merge them into state.json in this order: creativity → testing → developing → integrating → process_improvement. Disjoint write sets allow parallel spawn.

Slot-filling: after every supervisor return, check engine_slots.kimi.in_flight vs max_parallel=6. If slot open AND queued work exists → dispatch.

When uncertain about a design choice: dispatch 2-3 Kimi packets with alternative framings rather than agonizing alone (memory feedback_operator_inputs_become_harness_config).

================================================================
PART 8 — KILL CONDITIONS (when to STOP and wait for operator)
================================================================

Stop autonomous loop and surface to operator ONLY when:

1. L5 escalation per Part 2 criteria.
2. wave_plan has zero queued/in_progress items AND all rows in STATUS.csv are shipped/deferred/parked — i.e., done with backlog.
3. Operator types into chat (interruption is itself an event).
4. Three consecutive ticks with no actionable work (loop has caught up — emit status summary, await direction).

Otherwise: keep dispatching, integrating, status-csv-updating, slot-filling.

================================================================
PART 9 — MEMORY ENTRIES (load by name; in ~/.claude/projects/D--Projects/memory/)
================================================================

feedback_xaxiu_harness_full_dev_authority   — authority + L5-only escalation
reference_xaxiu_harness_error_taxonomy      — L1-L5 + domain + code scheme
feedback_xaxiu_swarm_backend_agentic_differences — kimi vs api backend behaviors
feedback_kimi_cli_incremental_edits         — swarm status lies; check git diff
reference_xaxiu_swarm_concurrency_calibration — 6/18/1 slot calibration from warehouse
feedback_operator_inputs_become_harness_config — Wave 7 origin + uncertainty → more Kimi rule
feedback_cross_engine_fallback               — never retry same engine on failure
feedback_multi_session_scoping               — don't cross into warehouse
feedback_engine_anchor_accuracy              — DeepSeek FIND drift; verify byte-exact
feedback_deepseek_v4_no_tools_packet         — --no-thinking + text-only for FIND/REPLACE
feedback_status_csv_canonical                — STATUS.csv discipline (now harness primitive per #19)
feedback_active_tracking_table               — mtime canary + two-line litmus
feedback_engine_dispatch_path                — xaxiu-swarm is the canonical dispatch tool
feedback_no_claude_swarm_worker              — never --backend claude
feedback_milestone_audit_discipline          — milestone:audit_dispatch + audit_complete events

================================================================
PART 10 — CRITICAL PATHS (when you need to find something fast)
================================================================

CLI: src/harness/cli.py + cli_helpers.py
Engines: src/harness/engines/{base,concrete,dispatcher,guards}.py
State: src/harness/state/{db,files,jsonl_log}.py
Operator: src/harness/operator/{__init__,modes,config,flags}.py
Errors: src/harness/errors.py + spec/errors.md
Secrets: src/harness/secrets/dpapi.py (Windows-only v0.x)
Adapters: src/harness/adapters/{loader,schema}.py + templates/*.yaml
Status (post-#19): src/harness/status/{__init__,schema,store,hooks}.py
Dev loop: coord/dev_loop/{manager,dispatch-rules}.md + state.json + supervisors/*.md + log.jsonl + escalations.md
STATUS tracker: coord/STATUS.csv (operator-readable), `harness status` CLI verbs (post-#19)
Tests: tests/test_*.py — 263 passing (will be 285+ after #19 + Wave 5 lands)
CI: .github/workflows/test.yml (ubuntu + windows × py3.13)
Scripts: bin/{install-harness.ps1, uninstall-harness.ps1, register-dev-loop-task.ps1, dev-loop-tick.ps1, parse-swarm-status.py}
Specs: spec/{errors, operator-modes, status-tracker, session-derived-feature-roster, wave-4-installer, wave-5-templates-nl-yaml, autonomous-loops}.md
Bootstrap (this file): coord/SESSION_BOOTSTRAP.md
Packets queued (highest priority first): coord/packets/2026-05-20-status-tracker-harness-feature/, then wave5A, wave5B, wave7C, heartbeat-cli-verb, state-inspect-cli-verb
Recent commits (top 5): ad67209 214ef51 74fe60b 04a60f0 bd26470

================================================================
PART 11 — DO NOT
================================================================

- Don't ask the operator anything below L5
- Don't use --backend claude
- Don't dispatch in-place-edit packets to swarm/kimi-api or swarm/deepseek
- Don't ignore the swarm status line, BUT don't trust it either — always git diff to verify
- Don't pause the entire loop on L3 (only the affected packet pauses)
- Don't claim "tests pass" without actually running pytest
- Don't claim "live" before final verification (curl smoke for any deploy)
- Don't touch D:\Projects\warehouse\* files (read-only pattern reference is fine)
- Don't update warehouse's STATUS.csv from this session
- Don't author code >30 LOC outside the harness scope (warehouse + other projects still have the 30-LOC ceiling)
- Don't add new memory entries about transient session events; only durable patterns
- Don't dispatch packets at --max-concurrent above 6 on swarm/kimi until empirically tested higher (current ceiling: 6 prod, 8 test, untested above)
- Don't dispatch status-tracker + Wave 5/B + W7C in the same swarm round (all touch cli.py — sequence them)

================================================================
End of bootstrap. First action: read the 10 boot files, smoke pytest, then dispatch the status-tracker packet (round 1). Status update only after each integration or at L5.
```

---

## Maintenance

When project state drifts materially (new supervisor, new memory entry, new wave shipped, calibration retuned), update the **Current state delta** section above + the critical-paths block in Part 10. The prompt body's protocol sections (Parts 2 / 3 / 5 / 6 / 7 / 8 / 11) are durable — only edit if a rule itself changes.

The bootstrap evolves with the project. Consider this artifact part of Wave 6 productization scope: eventually `harness session bootstrap` CLI verb emits the prompt with auto-updated state + critical-paths sections.
