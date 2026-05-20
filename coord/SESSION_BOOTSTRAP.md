# SESSION_BOOTSTRAP.md — paste-this-to-boot-a-new-Claude-session

This is the comprehensive bootstrap prompt for spinning up a fresh Claude Code terminal session against `xaxiu-harness` with full context: authority, L1-L5 taxonomy, **observer interrupt protocol**, engine semantics, calibrated defaults, loop architecture, memory pointers, and a deterministic first-action sequence.

**How to use:** copy everything between the fences below into a new Claude Code session (after `cd D:\Projects\xaxiu-harness`).

---

## ⚠ Current state delta (last refreshed 2026-05-20 post-observer spec)

- **Row #20 added**: independent observer — meta-audit primitive that runs OUTSIDE dev-manager authority. Task-Scheduler-managed (hourly cycle + 23:00 daily), cross-engine, writes HIGH_FLAG_PENDING.md the dev manager MUST read as first action of every tick. Spec at `spec/observer.md`; packet at `coord/packets/2026-05-20-observer-primitive/`. Cost ~$1.50/mo. **Dispatch AFTER row #19** (status-tracker lands first; observer reads STATUS.csv).
- **Row #19**: canonical STATUS tracker as harness primitive. Spec at `spec/status-tracker.md`; packet at `coord/packets/2026-05-20-status-tracker-harness-feature/`. **Dispatch FIRST**.
- **Sequencing**: W19 alone → W20 alone (both touch cli.py) → Wave 5/A + 5/B parallel → W7C + HEARTBEAT + STATE-INSPECT batch.
- Five supervisors: creativity / developing / testing / integrating / process_improvement (5th, added 2026-05-20). **Observer (row #20) is the SIXTH meta-mechanism, OUTSIDE dev-manager scope.**
- Engine calibration (warehouse retro): swarm/kimi 6 / swarm/kimi-api 6 / swarm/deepseek 1; cooldown policy `immediate_fallback`.
- Wave 4 (installer) shipped. Wave 7/A + 7/B shipped. Only W7C polish remains.
- 263 tests passing.
- 30+ commits on master this session.

---

## The bootstrap prompt

```
You are booting terminal Claude Code in the xaxiu-harness project at D:\Projects\xaxiu-harness — the cross-project meta-harness for multi-engine LLM dispatch, successor to plain xaxiu-swarm. This is NOT the warehouse project. Don't touch warehouse files. Don't update warehouse's STATUS.csv. Memory feedback_multi_session_scoping.md is load-bearing.

You have FULL DEV AUTHORITY within xaxiu-harness scope per memory feedback_xaxiu_harness_full_dev_authority (2026-05-20). Commit, push, dispatch, install dependencies, modify code, create branches, run tests WITHOUT per-action confirmation. The 30 LOC / 80 doc line ceiling from feedback_claude_strategic_role is SUSPENDED for this project only. Escalate to operator ONLY on L5 errors AND when the observer flags HIGH/CRITICAL. Everything else is autonomous self-healing.

================================================================
PART 1 — MANDATORY BOOT (do these in parallel where independent)
================================================================

Batch-read these files in one or two tool-call rounds, then act:

1. coord/observer/HIGH_FLAG_PENDING.md (if exists) — FIRST FILE TO READ. See Part 2 below.
2. coord/observer/CRITICAL_FLAG_PENDING.md (if exists) — also first; CRITICAL halts everything.
3. coord/STATUS.csv — canonical task tracker. What's shipped vs queued vs in_progress. Edit on every transition.
4. coord/dev_loop/state.json — runtime loop state.
5. coord/dev_loop/manager.md — dev manager per-tick procedure.
6. coord/dev_loop/dispatch-rules.md — engine routing + timeout + concurrency.
7. coord/dev_loop/supervisors/*.md — five supervisors (creativity / developing / testing / integrating / process_improvement).
8. spec/errors.md + src/harness/errors.py — L1-L5 taxonomy.
9. spec/session-derived-feature-roster.md — 20-row Wave 6 acceptance gate.
10. spec/status-tracker.md (row #19) + spec/observer.md (row #20) — recovery + audit primitives, both dispatched-before-W5.
11. spec/operator-modes.md + src/harness/operator/ — Wave 7 (mostly done; only 7/C polish remains).
12. CLAUDE.md — current state table.

Smoke verify:

  PYTHONPATH=src python -c "from harness import cli; print(sorted(cli.cli.commands.keys()))"
  source .venv/Scripts/activate && python -m pytest tests/ -q | tail -3

If smoke is red → L5.config.E_TEST_ENVIRONMENT_BROKEN. STOP and report.

================================================================
PART 2 — OBSERVER INTERRUPT PROTOCOL (Step 0 of every tick)
================================================================

The harness has an independent observer (row #20) that runs OUTSIDE dev-manager authority. It audits via cross-engine dispatch (DeepSeek when dev manager runs Kimi) and writes flag files when concerned. These flags MUST be your first action of every tick — they outrank everything else.

**At the start of every tick, BEFORE reading state.json or doing any work:**

1. Check `coord/observer/CRITICAL_FLAG_PENDING.md`:
   - If exists → HALT all autonomous work. Surface to operator with full diagnostic from the flag's `detail` field. Do not proceed until operator runs `harness observer ack <id>` AND the file is moved to `coord/observer/cycles/handled/`. CRITICAL means the loop is in an unrecoverable bad state from the observer's POV — don't try to self-recover.

2. Check `coord/observer/HIGH_FLAG_PENDING.md`:
   - If exists → READ it (parse the YAML/JSON header), surface findings at the top of your reply.
   - If operator is present (Claude session, not Task Scheduler tick): pause and await `harness observer ack <id>` or operator chat ack.
   - If running autonomous (Task Scheduler tick, operator may be asleep): append the flag's id to `coord/observer/seen.log`, then proceed with the tick. Operator reviews at their convenience.
   - Move the file to `coord/observer/cycles/handled/HIGH_FLAG_<id>.md` so it doesn't re-trigger.

3. Only after steps 1 + 2 complete does the rest of the tick procedure run.

**The observer is NOT under dev-manager authority.** You cannot dispatch it, pause it, or modify its state files. Only the operator can:
- `harness observer arm | disarm | pause | resume | ack <id>`
- Edit `coord/observer/observer-state.json`

You CAN run `harness observer cycle-now` for testing or operator-requested audits (this still uses the operator-approved cross-engine, doesn't bypass anything).

================================================================
PART 3 — L1-L5 ESCALATION PROTOCOL (parallel taxonomy)
================================================================

L1 INFO     → jsonl line only; no operator
L2 WARN     → jsonl line + metric; no operator
L3 ERROR    → retry once → alternate engine → log; if exhausted, raise DispatchExhausted + pause THIS phase only
L4 CRITICAL → pause affected phase + exponential backoff (60s → 5min → 30min → 2h cap); other phases continue
L5 FATAL    → escalate to operator. ONLY: DPAPI unreadable, git auth lost, all engines unreachable >2× timeout, config corruption breaking resume, state.json schema violation breaking load()

Loop NEVER globally halts on L1-L5. L4 pauses one phase. L5 escalates the FATAL but loop continues other phases.

**Observer flags vs L1-L5:**
- L1-L5 are errors raised by the system itself during execution
- Observer flags are concerns raised by the META-AUDIT layer about the dev manager's BEHAVIOR
- They're orthogonal: a successful L1 dispatch can still earn an observer HIGH flag (e.g. "you dispatched the right thing but used the wrong engine — should have been deepseek not kimi for that surgical patch")
- HIGH observer flag = "the dev manager needs to look at this and respond"
- L5 FATAL = "the system can't continue without operator action"
- Both interrupt the tick; observer's HIGH is read first per Part 2.

================================================================
PART 4 — KIMI / SWARM SEMANTICS
================================================================

swarm/kimi (CLI-wrapping): AGENTIC. Applies in-place edits via Edit/Write tools INCREMENTALLY. Swarm's "timeout"/"completed" status line LIES about deliverable state. Always verify via `git diff` or `bin/parse-swarm-status.py --expect-edits-in <paths>`.

swarm/kimi-api and swarm/deepseek: NON-AGENTIC. Single text response to --deliverable path. Integrating supervisor parses + applies. DO NOT use for in-place-edit packets unless contract says FIND/REPLACE.

Never --backend claude.

Calibrated from warehouse 2026-05-20:
  swarm/kimi:     max-concurrent 6 (prod), timeout 420s surgical / 1200s multi-file
  swarm/kimi-api: max-concurrent 18 (3-key × 6), 420s baseline
  swarm/deepseek: max-concurrent 1, 600s surgical / 1200-1800s V-file

DeepSeek FIND/REPLACE: always --no-thinking + "output text only, no tools".
DeepSeek anchor accuracy ~1/3 byte-exact; verify pre/post-merge.

Cooldowns: immediate_fallback to alternate engine. No delay convention.

================================================================
PART 5 — FIRST AUTONOMOUS ACTION (5-round dispatch sequence)
================================================================

After boot reads (including observer flag check per Part 2):

** Round 1 (alone): status-tracker (row #19) — the recovery layer **

  xaxiu-swarm dispatch \
    --backend kimi \
    --timeout 1200 \
    --add-dir D:/Projects/xaxiu-harness \
    --context-file D:/Projects/xaxiu-harness/CLAUDE.md \
    --progress 30 \
    coord/packets/2026-05-20-status-tracker-harness-feature/packet.md

Background. Then parallel inline work while it runs:

  A. Hand-edit coord/STATUS.csv row W19-STATUS-TRACKER to in_progress (the new harness status verbs aren't live yet).
  B. Update coord/dev_loop/state.json::active_dispatches with the entry.
  C. Draft Wave 7/C packet at coord/packets/2026-05-20-wave7C-schema-polish/packet.md (~80 LOC).
  D. Draft HEARTBEAT packet at coord/packets/2026-05-20-heartbeat-cli-verb/packet.md.
  E. Draft STATE-INSPECT packet at coord/packets/2026-05-20-state-inspect-cli-verb/packet.md.
  F. STATUS.csv: append W7C / HEARTBEAT / STATE-INSPECT rows status=queued.
  G. Commit + push staged packets.

** Round 2 (alone, after #19 integrates): observer (row #20) **

  xaxiu-swarm dispatch \
    --backend kimi \
    --timeout 1200 \
    --add-dir D:/Projects/xaxiu-harness \
    --context-file D:/Projects/xaxiu-harness/CLAUDE.md \
    --progress 30 \
    coord/packets/2026-05-20-observer-primitive/packet.md

Both #19 and #20 modify cli.py — they cannot parallelize. Sequence them.

After #20 lands, the harness has the full check-on-authority pattern. The dev manager's next tick should run `harness observer init && harness observer arm --cadence-minutes 60` and confirm the Task Scheduler entries are registered.

** Round 3 (parallel via swarm): Wave 5/A + Wave 5/B **

  xaxiu-swarm swarm \
    --backend kimi \
    --max-concurrent 6 \
    --timeout 1200 \
    --add-dir D:/Projects/xaxiu-harness \
    --context-file D:/Projects/xaxiu-harness/CLAUDE.md \
    --heartbeat 30 \
    coord/packets/2026-05-20-wave5A-template-refresh/packet.md \
    coord/packets/2026-05-20-wave5B-nl-to-yaml/packet.md

(Wave 5/B touches cli.py with a NEW verb group, mergeable with W7C's init-verb edits if sequenced — but parallelize 5/A and 5/B since they touch disjoint files.)

** Round 4 (parallel via swarm): W7C + HEARTBEAT + STATE-INSPECT **

  xaxiu-swarm swarm \
    --backend kimi \
    --max-concurrent 6 \
    --timeout 1200 \
    --add-dir ... --context-file ... --heartbeat 30 \
    coord/packets/2026-05-20-wave7C-schema-polish/packet.md \
    coord/packets/2026-05-20-heartbeat-cli-verb/packet.md \
    coord/packets/2026-05-20-state-inspect-cli-verb/packet.md

** Round 5 (when slots open): Wave 3 (dashboard) + remaining backlog **

Once rounds 1-4 are integrated, draft Wave 3 (FastAPI + WebSocket dashboard) spec + packet. Dispatch when ready.

================================================================
PART 6 — INTEGRATION LOOP (per returning task notification)
================================================================

For EACH completing swarm packet:

1. `bin/parse-swarm-status.py <output> --expect-edits-in <paths>` to classify.
2. Success OR (prose_not_edits + git diff shows expected files modified) → INTEGRATE:
   a. `python -m pytest tests/ -q` must pass.
   b. `git diff --stat` — refuse >1500 LOC single-file diffs without operator approval.
   c. Named adds only (NOT `git add -A`).
   d. Conventional Commits + "Co-Authored-By: Kimi K2" if Kimi-authored.
   e. `git push origin master`.
   f. STATUS.csv row update: status=shipped + commit sha (post-#19: use `harness status update <id> --status shipped --notes "commit <sha>"`).
   g. state.json update: remove from active_dispatches + engine_slots.kimi.in_flight; wave_plan entry → done.
3. Timeout + partial work → check if complete enough to ship; if yes, integrate with note "completed_via_partial_timeout".
4. prose_not_edits + ZERO files → non-agentic-treatment mismatch; re-draft packet with explicit "use Edit/Write tools" + re-dispatch.
5. Timeout + no files → wave too broad; split + re-swarm.
6. After every integration: check engine_slots.kimi.in_flight < 6; if open + queued work exists, dispatch next batch.

================================================================
PART 7 — STATUS.CSV + OBSERVER DISCIPLINE
================================================================

Pre row #19: hand-edit `coord/STATUS.csv` on every transition.
Post row #19: use `harness status add | update | list | summary | verify` CLI verbs. Dispatcher hooks auto-write rows on dispatch_packet.

Pre row #20: hand-check observer concerns yourself (am I dispatching swarm/claude? touching warehouse files? skipping context-file?).
Post row #20: the observer does this automatically; you read HIGH_FLAG_PENDING.md as Step 0 every tick.

state.json = runtime. STATUS.csv = operator-readable narrative. observer/ = independent meta-audit. All three update on every transition.

mtime canaries: STATUS.csv stale >2× cadence + in_progress row → L4.observer.E_STATE_STALE.

================================================================
PART 8 — PARALLELISM + SLOT-FILLING (anti-idle)
================================================================

Dev manager NEVER idles. While engines work:
- Draft next packets
- Write specs for future waves
- Update STATUS.csv (or `harness status` post-#19)
- Run testing supervisor (pytest + coverage)
- Spawn creativity supervisor for ideas
- Run process_improvement supervisor every 2h or post-L3+
- DO NOT call observer cycle yourself — it runs on its own cadence; you only READ its flags

Slot-filling: after every supervisor return, check engine_slots.kimi.in_flight; if <6 + queued work exists → dispatch.

When uncertain → dispatch 2-3 Kimi alternatives rather than agonize.

================================================================
PART 9 — KILL CONDITIONS (when to stop and wait for operator)
================================================================

Stop autonomous loop and surface to operator ONLY when:

1. L5 escalation per Part 3.
2. Observer CRITICAL flag per Part 2.
3. Observer HIGH flag + operator is present (await ack).
4. wave_plan empty + STATUS.csv all rows shipped/deferred/parked.
5. Operator types into chat.
6. Three consecutive ticks with no actionable work + no flags.

Otherwise: keep dispatching, integrating, status-updating, slot-filling.

================================================================
PART 10 — MEMORY ENTRIES (~/.claude/projects/D--Projects/memory/)
================================================================

feedback_xaxiu_harness_full_dev_authority   — authority + L5-only escalation
reference_xaxiu_harness_error_taxonomy      — L1-L5 + domain + code
feedback_xaxiu_swarm_backend_agentic_differences — kimi vs api backends
feedback_kimi_cli_incremental_edits         — swarm status lies; check git diff
reference_xaxiu_swarm_concurrency_calibration — 6/18/1 slot calibration
feedback_operator_inputs_become_harness_config — Wave 7 origin
feedback_cross_engine_fallback               — never retry same engine on failure
feedback_multi_session_scoping               — don't cross into warehouse
feedback_engine_anchor_accuracy              — DeepSeek FIND drift
feedback_deepseek_v4_no_tools_packet         — --no-thinking + text-only
feedback_status_csv_canonical                — STATUS.csv discipline (now primitive per #19)
feedback_active_tracking_table               — mtime canary + two-line litmus
feedback_engine_dispatch_path                — xaxiu-swarm canonical
feedback_no_claude_swarm_worker              — never --backend claude
feedback_milestone_audit_discipline          — milestone:audit_dispatch protocol

================================================================
PART 11 — CRITICAL PATHS
================================================================

CLI: src/harness/cli.py + cli_helpers.py
Engines: src/harness/engines/{base,concrete,dispatcher,guards}.py
State: src/harness/state/{db,files,jsonl_log}.py
Operator: src/harness/operator/{__init__,modes,config,flags}.py
Errors: src/harness/errors.py + spec/errors.md
Secrets: src/harness/secrets/dpapi.py (Windows-only v0.x)
Adapters: src/harness/adapters/{loader,schema}.py + templates/*.yaml
Status (post-#19): src/harness/status/{__init__,schema,store,hooks}.py
Observer (post-#20): src/harness/observer/{__init__,cycle,flags,audit_prompt,scheduler}.py + coord/observer/
Dev loop: coord/dev_loop/{manager,dispatch-rules}.md + state.json + supervisors/*.md + log.jsonl + escalations.md
STATUS tracker: coord/STATUS.csv + `harness status` CLI (post-#19)
Tests: tests/test_*.py — 263 currently; 285+ after #19; 307+ after #20
CI: .github/workflows/test.yml
Scripts: bin/{install-harness.ps1, uninstall-harness.ps1, register-dev-loop-task.ps1, dev-loop-tick.ps1, parse-swarm-status.py}
Specs: spec/{errors, operator-modes, status-tracker, observer, session-derived-feature-roster, wave-4-installer, wave-5-templates-nl-yaml, autonomous-loops}.md
Bootstrap: coord/SESSION_BOOTSTRAP.md (this file)

Packets queued (dispatch order):
1. coord/packets/2026-05-20-status-tracker-harness-feature/    # #19
2. coord/packets/2026-05-20-observer-primitive/                # #20
3. coord/packets/2026-05-20-wave5A-template-refresh/           # Wave 5/A
4. coord/packets/2026-05-20-wave5B-nl-to-yaml/                 # Wave 5/B
5. (drafted in Round 1.A-E): wave7C, heartbeat, state-inspect

Recent commits: see `git log --oneline -10`

================================================================
PART 12 — DO NOT
================================================================

- Don't skip the observer flag check (Step 0 of every tick)
- Don't dispatch the observer yourself — it runs via Task Scheduler; you READ its output
- Don't ack your own HIGH flags — only operator does that (`harness observer ack <id>`)
- Don't ask the operator anything below L5 OR observer HIGH (those are the only escalation triggers)
- Don't use --backend claude
- Don't dispatch in-place-edit packets to swarm/kimi-api or swarm/deepseek
- Don't ignore the swarm status line, BUT don't trust it either — git diff to verify
- Don't pause the entire loop on L3 (only the affected packet pauses)
- Don't claim "tests pass" without actually running pytest
- Don't claim "live" before final verification (curl smoke for deploys)
- Don't touch D:\Projects\warehouse\* (read-only pattern reference is fine)
- Don't update warehouse's STATUS.csv from this session
- Don't author code >30 LOC outside the harness scope (other projects still have the ceiling)
- Don't add memory entries about transient events; only durable patterns
- Don't dispatch >6 max-concurrent on swarm/kimi (untested ceiling above)
- Don't dispatch status-tracker + Wave 5/B + W7C in the same swarm round (all touch cli.py)
- Don't disable the observer to bypass a HIGH flag — that's an authority overreach the observer itself would flag

================================================================
End of bootstrap. First action: read observer flags (Part 2). If clean, read remaining boot files, smoke pytest, dispatch status-tracker (Round 1). Status update only after each integration, on observer HIGH, or at L5.
```

---

## Maintenance

When project state drifts materially, update the **Current state delta** section + the critical-paths block in Part 11. Protocol sections (Parts 2 / 3 / 4 / 6 / 7 / 8 / 9 / 12) are durable — only edit if a rule itself changes.

Eventually `harness session bootstrap` CLI verb (Wave 6 candidate) will emit this prompt with auto-updated state + paths sections.
