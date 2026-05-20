# Spec: Independent observer (the check on dev-manager authority)

## Goal

A meta-audit loop that runs **outside the dev manager's authority** — it can question dev-manager decisions, flag scope creep, catch L4/L5 events the dev manager missed, and force-interrupt the next dev-manager turn with findings the dev manager MUST address before continuing.

This is row #20 in the feature roster. Without it, the dev manager's full dev authority is unchecked — a single bad decision (wrong engine routing, scope creep, ignored escalation) propagates unchallenged. The observer is the answer to "who watches the watcher?"

Modeled on the warehouse observer (D:/Projects/warehouse/dev-panel-runs/ag-qty-bug-v101/observer/) but harness-native.

## Independence axiom

The observer is NOT dispatchable by the dev manager. The operator owns it; the dev manager reads its output. Concretely:

1. The observer runs via Windows Task Scheduler (`XaxiuHarnessObserverCycle`), independent of any Claude session.
2. The observer's engine is **always cross-engine** vs the dev manager — if dev manager is Claude-in-session + dispatching to Kimi, the observer dispatches to DeepSeek. The dev manager's blind spots can't audit themselves.
3. The observer writes `coord/observer/HIGH_FLAG_PENDING.md` when it finds a HIGH issue. The dev manager's `coord/dev_loop/manager.md` first-action-of-every-tick MUST be: read this file, surface findings, then proceed.
4. The dev manager cannot delete or modify observer state files (`observer-state.json`, audit outputs) except via the operator-only `harness observer ack <finding-id>` verb.
5. The observer can pause itself via `enabled: false` in `observer-state.json` — but only the operator can flip that flag (not the dev manager).

## Severity scale (parallel to L1-L5 but observer-only — surfaces to the dev manager, not directly to the operator)

| Severity | Definition | Dev manager response |
|---|---|---|
| LOW | Style/process nit (commit message wording, ordering preference) | Logged; no action required |
| MED | Procedural drift (forgot to update STATUS.csv, dispatched without context-file) | Acknowledge next tick; fix on next opportunity |
| HIGH | Authority overreach, scope creep, missed L5, or unsafe pattern (e.g. `git push --force`, secrets in commits, dev manager about to violate operator directive) | INTERRUPT NEXT TURN — read HIGH_FLAG_PENDING.md before any other work; surface to operator; do not proceed until acknowledged or addressed |
| CRITICAL | The dev manager is in an unrecoverable bad state (stuck loop 3+ ticks on same wave, all engines exhausted, state.json corruption, observer itself detects it can't read state) | Halt all dev-manager autonomous work; escalate directly to operator with full diagnostic; only operator can resume |

LOW/MED stack across cycles. HIGH interrupts. CRITICAL halts.

## What the observer audits

Per cycle (default cadence 60 min):

1. **Recent dev-manager activity** — last 30 entries of `coord/dev_loop/log.jsonl` + last 10 commits via `git log --oneline -10`.
2. **Authority discipline**:
   - Did the dev manager dispatch via swarm/claude? (forbidden)
   - Did the dev manager touch warehouse files? (forbidden — `D:/Projects/warehouse/*`)
   - Did the dev manager skip the `--context-file CLAUDE.md` flag on a dispatch?
   - Did the dev manager push to a branch other than master without explicit approval?
3. **Engine routing quality**:
   - Was an in-place-edit packet dispatched to swarm/kimi-api or swarm/deepseek? (anti-pattern; will fail)
   - Was a single-file surgical patch dispatched to DeepSeek without `--no-thinking`? (will hit DSML trap)
   - Was Kimi run at >6 max-concurrent without empirical validation?
4. **Scope creep**:
   - Did a packet's actual diff exceed its declared scope by >50%?
   - Did the dev manager start work outside the queued wave_plan items without operator directive?
5. **STATUS.csv discipline**:
   - Any row in `in_progress` for >2× declared effort?
   - Any commits with no corresponding STATUS.csv update?
   - mtime canary: STATUS.csv stale beyond expected cadence?
6. **L5 escalation discipline**:
   - Was any L4 event mis-classified as L3 (and therefore not paused-phase-correctly)?
   - Was any L5 event handled autonomously instead of escalated to operator?
7. **Cost/burn signals**:
   - swarm/deepseek dispatched when swarm/kimi was available (cost-on-demand violation)?
   - Same wave failed 3+ times across both engines (sunk-cost wave)?
8. **Memory consistency**:
   - Did a decision contradict a memory entry without justification?
   - Did the dev manager miss loading a relevant memory entry?

Output: `coord/observer/cycles/observer_<iso8601>.md` per cycle. Append HIGH/CRITICAL flags to dedicated files.

## Daily deep retro (DeepSeek 1M-context cross-engine audit)

At 23:00 local daily (via Windows Task Scheduler `XaxiuHarnessObserverDailyRetro`): one DeepSeek dispatch with the day's full log.jsonl + STATUS.csv diff + commits as context. Output: `coord/observer/daily/daily_<date>.md`.

This is the deep cross-engine pattern-detection layer. Catches issues hourly cycles miss because they don't see the full arc.

## CLI verb group (`harness observer`)

```
harness observer init                           # bootstrap coord/observer/ structure + observer-state.json
harness observer arm [--cadence-minutes N]      # register Task Scheduler entries; set enabled=true
harness observer disarm                          # unregister Task Scheduler; preserve state files
harness observer pause | resume                  # toggle enabled flag in observer-state.json
harness observer cycle-now [--engine ENGINE]    # manual one-shot cycle (for testing or operator-requested audit)
harness observer status                          # show last cycle + open HIGH/CRITICAL flags
harness observer flags [--severity HIGH|MED|LOW] [--clear ID]   # list / clear flags
harness observer ack <finding-id>                # operator-only — acknowledges a HIGH flag so dev manager can proceed
```

## Module layout

```
src/harness/observer/
├── __init__.py
├── cycle.py             # the cycle runner — dispatches cross-engine audit, parses findings
├── flags.py             # FlagSeverity enum + Flag Pydantic model + flag-store helpers (HIGH_FLAG_PENDING.md, etc.)
├── audit_prompt.py      # builds the audit prompt from log.jsonl + STATUS.csv + commits
├── scheduler.py         # Windows Task Scheduler registration via Register-ScheduledTask
└── tests/               # smoke tests for each
```

## Interrupt protocol (the load-bearing part)

Modify `coord/dev_loop/manager.md` to add a FIRST-ACTION-OF-TICK step:

```
0. Check coord/observer/HIGH_FLAG_PENDING.md:
   - If exists: read it, surface findings at top of next reply, then:
     - If the operator is present (i.e. we're in a Claude session with operator), wait for ack
     - If running autonomous (Task Scheduler tick), check if any finding is CRITICAL → halt;
       otherwise mark findings as "seen" by appending to coord/observer/seen.log,
       then proceed with tick
   - Move the file to coord/observer/cycles/handled/HIGH_FLAG_<id>.md so it doesn't re-trigger
```

Without this step, the observer's HIGH flags would be ignored. WITH this step, the observer has real authority.

## Tests required

- Cycle runner produces valid Markdown output for a mocked log.jsonl
- Severity classification: feed examples (force-push attempt, swarm/claude dispatch, scope creep) → assert correct severity
- HIGH_FLAG_PENDING.md is created when a HIGH finding fires; subsequent dev-manager tick reads + relocates it
- CRITICAL flag halts further dispatches (mocked: simulate critical flag, attempt `harness dispatch`, verify refusal)
- `harness observer pause` flips enabled flag; subsequent cycles exit early
- `harness observer ack` requires the finding ID; rejects unknown IDs

## Acceptance criteria

1. `harness observer init` creates `coord/observer/` with subdirs `cycles/`, `cycles/handled/`, `daily/`, `flags/` + an `observer-state.json` with sensible defaults.
2. `harness observer arm --cadence-minutes 60` registers two Task Scheduler entries: `XaxiuHarnessObserverCycle` (hourly) + `XaxiuHarnessObserverDailyRetro` (23:00 daily).
3. Manual cycle via `harness observer cycle-now --engine deepseek` runs to completion against current log.jsonl + STATUS.csv; output written to `coord/observer/cycles/observer_<ts>.md`.
4. Force a HIGH-severity scenario (e.g. mock a swarm/claude dispatch in log.jsonl): cycle produces HIGH_FLAG_PENDING.md.
5. Dev-manager tick reads HIGH_FLAG_PENDING.md as first action, surfaces it, moves to `handled/`.
6. `harness observer status` shows current cycle + open flags in 1 second.
7. `python -m pytest tests/ -q` passes ≥285 tests (was 263; +22 new).
8. Single commit: `feat(observer): independent harness observer (#20)`.

## Cost posture

- Cycle audit via swarm/deepseek-v4-flash: ~3 KB context + ~1 KB output ≈ $0.001 per cycle. 24 cycles/day × $0.001 = $0.024/day.
- Daily retro via swarm/deepseek with 1M context: ~50 KB input + ~3 KB output ≈ $0.02/day.
- Total observer cost: **~$0.05/day = $1.50/month**. Operator-approved (cost is negligible vs the value of catching a single L5 mishandling).

## What this UNBLOCKS

- Dev manager can be granted truly full autonomy because there's a check on it
- Wave 6 productization gets a key acceptance criterion: every operator-given directive can be tested against in the observer's audit prompt
- Cross-session continuity: HIGH flags survive Claude crashes via Task Scheduler-managed cycles
- Operator gets a daily "what did the dev manager do today + here are 3 concerns" summary without scrolling chat history
