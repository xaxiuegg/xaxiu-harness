# SPEC-ID: wave-8-plan — Tighten the detection layer (Track A) +
# operator-readiness foundation (Track B)

**Authored**: 2026-05-23 from TWO 10-reviewer panels:

1. The interaction-arc panel (Track A theme) — analysed the W6→W7
   workflow and converged on "tighten the detection layer" (stop-hook
   noise, audit-prompt truncation, observer-as-passive-surface).

2. The readiness panel (Track B theme) — assessed whether the harness
   is ready for the non-technical operator's daily use.  Verdict
   from all 10 reviewers: WITH GUARDRAILS or NO — **zero YES votes**.
   Convergent blockers: no `harness preflight --fix` auto-remediation,
   no plain-language daily runbook, no `harness status --human`,
   recovery paths require Python/git knowledge.

**Reshape** (operator decision pending): if Track B (readiness)
matters more than Track A (detection layer) for the operator's actual
use case, the W8 priority order swaps.  Track A's warm-up fixes
(stop-hook + audit-prompt) still ship in Phase A because they're cheap
+ unblock retroactive audits; everything else reorders to lead with
operator-readiness.

The unedited prior W8 plan follows.  Track B addendum is at the
bottom of this doc.

**Theme** (panel-converged across M2 / M3 / M5 / K1 / K2): **tighten
the detection layer**.  Wave 7 left the execution layer (worker
pipeline, transport ABC, mutation infrastructure) strong.  What's
weak is *automated feedback*: the stop-hook fires on mtime churn,
audit gates required 3 retries to articulate criteria, no guard
against silent empty engine responses, no canary sampling beyond
the W6-A3 hot modules.

## Why this wave

W7 shipped 8 of 8 backlog rows + 2 panel-surfaced bonuses with 0 audit
STOPs in real time — but the retroactive W7 audit sweep then produced
4 STOPs (CLOSEOUT 0.62, MUTATION-ORCH 0.62, KIMI-MAX-TOKENS-FLOOR 0.40,
SPEC-DRIFT 0.40).  All 4 STOPs reflect *detection-layer noise*: the
audit script truncated diffs and the auditor couldn't see the
implementation.  The implementation was correct; the detection layer
made the auditor unable to say so.

The interaction panel converged on this pattern.  Wave 8 fixes it.

## Phases

### Phase A — Warm-up: noise reduction (~1 hr; ships in the first 90 min)

#### W8-STOP-HOOK — content-hash + debounce + path exclusions (~30 min)

Per panel 8/10 vote: stop-hook fires constantly on mtime drift during
mutation sweeps, audit-script writes, and any side-effect file touch.

**Steps**:
1. Layer 1: content-hash check.  If working-tree STATUS.csv matches
   `git show HEAD:coord/STATUS.csv` AND the last commit touched
   STATUS.csv within 60 min, the hook exits silently regardless of
   mtime of other files.  (K3/K5/M2 idea.)
2. Layer 2: debounce.  Don't fire more than once per 5 min.  State
   in `.claude/.stop-hook-last-fire`.  (K3/M1/M2/M4 idea.)
3. Layer 3: extended path exclusions — exclude `coord/reviews/*`,
   `spec/auto/*`, `.pytest_cache/*` from the find target list.  These
   are dispatch / review artifacts, not task state.

**Acceptance**:
- ≥3 turns of mutation-sweep work produce ZERO hook fires
- Hook still fires when real harness files (src/harness/*.py,
  tests/*.py) are modified without STATUS.csv update within 5 min
- Existing test suite passes

#### W8-AUDIT-PROMPT — raise truncation limits + head+tail strategy (~15 min)

Root cause of 4/9 W7 audit STOPs.  MiMo has a 131K input window;
limits at 16K diff + 12KB files were way too tight.

**Steps**:
1. Raise diff limit 16000 → 48000 chars.
2. Raise per-file budget 3000 → 8000 chars.
3. Raise file cap 4 → 10 files.
4. When content exceeds the limit, use head+tail strategy (60%/40%)
   instead of just head — most Python modules put the primary exports
   near the end after helpers.

**Acceptance**:
- Re-audit the 4 W7 STOPs (CLOSEOUT, MUTATION-ORCH, KIMI-MAX-TOKENS-
  FLOOR, SPEC-DRIFT) — each should now PASS at ≥0.7 since the auditor
  can see the implementation.
- Audit-prompt total stays well under MiMo's 131K window even with
  the higher limits.

### Phase B — Boundary-harden untrusted perimeter (per K2 panel signal)

#### W8-MUTATION-CANARY — 3-mutant rolling spot-check (~1 hr)

K2 panel insight: the W6-A3 sweep covered 5 hot modules but left
proxy/, observer/, loops/, dashboard/ untested.  A full sweep of
4 more modules is expensive (~15 min wall clock).  Instead, run a
rolling 3-mutant canary against one module per session and rotate.

**Steps**:
1. `scripts/run_mutation_canary.py`: applies 3 (not 5) mutations to
   one module at a time.  Same str.replace pattern.
2. Default rotation order: proxy/dispatch.py → observer/hook.py →
   loops/scheduler.py → dashboard/state.py.
3. Output: per-module pass/fail with the kill rate; same report
   format as the full sweep.
4. Add to `harness preflight` as a "canary sample passed last 24h"
   row.

**Acceptance**:
- Canary script runs in <3 min wall clock
- One module per run; rotation auto-cycles
- Each module surveyed reaches ≥3 kill rate OR gets a follow-up row
  (same pattern as W6-A3 follow-ups)

#### W8-PROXY-MUTATION-KILL + observer + loops + dashboard (if canary finds 0-rate)

Per W6-A3 + W7-MUTATION-* template: if the canary surfaces a
0-kill module, add behavioral tests until that module reaches the
threshold.  Queued as conditional rows (only fire if canary fails).

### Phase C — Promote observer to first-class operator surface (per K3/M1/M5)

#### W8-OBSERVER-DASHBOARD — turn observer logs into a queryable surface (~2 hr)

K3/M1/M5 converged: observer is currently a passive sentinel writing
to coord/observer/.  Promote it to a queryable dashboard at /v2/
observer/ with audit-STOP history, mutation-kill trend, transport
health, dead-engine alarm timeline.

**Steps**:
1. Read existing observer state (coord/observer/cycles/, flags, etc.)
2. New dashboard route `/v2/observer` with summary + table view
3. CLI verb `harness observer summary` for non-dashboard access
4. Promote critical flags to STATUS.csv (so operator sees them in the
   one canonical place)

**Acceptance**:
- Operator can answer "what's the observer worried about right now?"
  from one command/page
- ≥5 unit tests on the new view layer

### Phase D — Engine layer consolidation (per M1/M3)

#### W8-TRANSPORT-REDUNDANCY — SSE-drop fallback (~1.5 hr)

M3 panel finding: StreamingTransport ABC silently kills DeepSeek +
Kimi if SSE breaks mid-stream.  Need a fallback to batch HTTP.

**Steps**:
1. Add `_fallback_batch_dispatch` hook to StreamingTransport
2. KimiConcrete + DeepSeekConcrete implement it pointing to their
   non-streaming endpoints
3. Hook fires when streaming raises RemoteProtocolError AND
   accumulated content is empty
4. Tests cover the fallback path + verify total wall clock < 2x
   streaming attempt

**Acceptance**:
- Streaming failure → batch HTTP retry → real content
- Test exercises mid-stream disconnect → fallback
- Latency budget honored

### Phase E — Closeout

#### W8-CLOSEOUT — wave-closeout doc with re-audit of warm-up STOPs

**Steps**:
1. Re-run the W7 audit STOPs with the new audit-prompt limits to
   confirm Phase A fixes the noise.
2. Author coord/reviews/wave-8-closeout.md summarising the wave.
3. Run readiness-assessment panel as a delta from this wave's
   baseline to see what moved.

**Acceptance**:
- All 4 prior W7 STOPs now PASS at ≥0.7 with the new audit script
- W8 own rows audit clean
- Readiness panel scores ≥1 dimension higher than the pre-W8 baseline

## What's NOT in Wave 8

- ❌ K5 devil's advocate: "suspend MiMo audit, use machine-checkable
  grammar instead".  Hold this — if Phase A noise reduction works,
  the audit gate isn't broken (just under-budgeted).  Revisit at W9
  if STOPs persist post-W8.
- ❌ K3 state-layer compression (JSONL + JSON → SQLite).  Significant
  refactor.  Queue as W9 candidate.
- ❌ M5 config-drift audit.  Defer — no specific drift incident to
  motivate the work yet.
- ❌ K4 audit-router (MiMo → DeepSeek failover).  Defer — no MiMo
  quota incident yet; the W6-PANEL retry hit max_tokens, not quota.
- ❌ K1 panel-synthesis.md template codification.  Small + valuable;
  could ship as a docs commit if convenient, but not load-bearing
  for the W8 theme.

## Audit gate (per W7-AUDIT-POLICY, all Wn)

Every shipped W8 row runs through `scripts/audit_task_with_mimo.py
<task-id> --commit <sha>` after landing.  Phase A's W8-AUDIT-PROMPT
fix happens FIRST so subsequent W8 audits don't hit the truncation
noise.

## Effort estimate

| Phase | Effort | Risk |
|---|---|---|
| A — warm-up noise reduction | ~1 hr | Low |
| B — canary + remediation | ~1-3 hr | Medium (depends on findings) |
| C — observer dashboard | ~2 hr | Medium (UI work) |
| D — transport redundancy | ~1.5 hr | Medium (engine integration) |
| E — closeout | ~30 min | Low |
| **Total** | **~6-8 hr** | — |

Same wall-clock budget as W6 + W7.  Risk envelope is centred on
Phase B (depends on what the canary finds) and Phase C (new UI
surface; mocked tests likely insufficient).

---

# Track B addendum — operator-readiness foundation

From the 10-reviewer readiness panel (2026-05-23, 163s parallel
elapsed).  The harness is engineering-grade (1544 tests, 7 waves
shipped) but **operator-unsafe** for non-technical daily use per
the panel's unanimous verdict.

## Rubric averages (rough across 10 reviewers, 0-5 scale)

| Dimension | Score | Convergent finding |
|---|---|---|
| Install | ~2.3 | preflight fails on pytest_cache + git_clean + dead_engines; recovery requires Python/git knowledge |
| Daily run | ~3.0 | `morning-brief` is good, but no obvious daily sequence; 60+ subcommands |
| Observe | ~3.8 | STATUS.csv + dashboard + observer flags work, but STATUS.csv has UUIDs + commit hashes + 269 rows (developer-grade) |
| Recover | ~2.0 | "rotate keys", "fix pytest", "stash git" all assume technical knowledge — no `--fix` flag, no auto-quarantine |

## Convergent blockers (≥5 of 10 reviewers)

#### W8-PREFLIGHT-FIX — `harness preflight --fix` auto-remediation (~2 hr) ⭐

**8/10 reviewers** (K1/K2/K3/K4/M1/M3/M4/M5) request this.  Right now
when `harness preflight` shows dead engines, dirty git, or pytest
cache failures, the operator has no remedy except running raw git/
pytest/JSONL inspection.

**Acceptance**:
- `harness preflight --fix` auto-remediates 3 common failures:
  - Dirty git: `git stash` with operator confirmation
  - Stale pytest cache: clear `.pytest_cache/v/cache/lastfailed`
  - Dead engines: auto-quarantine via engine_health.json + L4 toast
- Output is plain-language ("Stashed your changes — you can pop them
  later with `git stash pop`") not technical jargon
- Each fix has a `--dry-run` preview mode
- 0-knowledge operator can run it and land on green preflight

#### W8-OPERATOR-RUNBOOK — single-page daily runbook for non-technical operators (~1 hr) ⭐

**6/10 reviewers** (K1/K2/K3/K4/K5/M2) request this.  Right now there
are 4 docs an operator might read first (README, CLAUDE.md,
SESSION_BOOTSTRAP, MIGRATION.md) and 60+ subcommands they could pick
from.  No "daily playbook" exists.

**Acceptance**:
- `docs/OPERATOR_RUNBOOK.md` (or `coord/OPERATOR.md`) with EXACTLY
  3-5 commands the operator runs every morning + EXACTLY 3-5
  remediation paths for every preflight failure (plain language,
  not Python)
- Linked from README's first line
- ≤2 minutes to scan; no commit hashes, no UUIDs, no Python code

#### W8-STATUS-HUMAN — `harness status --human` plain-language daily view (~1.5 hr) ⭐

**5/10 reviewers** (K2/K4/K5/M2/M4) request this.  STATUS.csv has 269
rows of dev-state.  The operator wants a "what happened, what's
broken, what to do" pulse.

**Acceptance**:
- New CLI verb `harness status` (or `harness today`) prints in <10s
- Sections: (1) overnight run summary, (2) current blockers in plain
  English, (3) next 1-3 actions
- Hides UUIDs, commit hashes, internal task IDs (or labels them
  parenthetically)
- ≥3 tests covering the human-renderer

#### W8-ENGINES-HEAL — `harness engines heal` one-command engine recovery (~1 hr)

**4/10 reviewers** (K1/K3/K4/K5) request this.  When an engine goes
dead (5 consecutive failures, the W6-C2 alarm fires), the operator
sees the toast but can't act on it.

**Acceptance**:
- `harness engines heal` quarantines dead engines, attempts key
  re-load from DPAPI, surfaces a plain-language report
- Integrates with the W6-C2 dead-engine alarm so the L4 toast can
  link to "run this command"
- ≥3 tests covering quarantine + re-load + report paths

## Track B effort estimate

| Row | Effort | Operator-impact priority |
|---|---|---|
| W8-PREFLIGHT-FIX | ~2 hr | ⭐⭐⭐ (8/10 panel) |
| W8-OPERATOR-RUNBOOK | ~1 hr | ⭐⭐⭐ (6/10 panel) |
| W8-STATUS-HUMAN | ~1.5 hr | ⭐⭐ (5/10 panel) |
| W8-ENGINES-HEAL | ~1 hr | ⭐⭐ (4/10 panel) |
| **Track B total** | **~5.5 hr** | — |

## Recommended W8 reshape

If operator agrees Track B (readiness) outweighs Track A (detection
layer):

1. **Phase A unchanged**: ship stop-hook + audit-prompt fixes in
   first 60 min (already complete as of commit `<TBD>`).
2. **Phase B-revised**: Track B rows ship NEXT — preflight --fix,
   operator runbook, status --human, engines heal.  ~5.5 hr.
3. **Phase C onwards**: original Track A items (mutation canary,
   observer-as-operator-surface, transport redundancy) deferred to
   Wave 9 OR shipped after Track B if budget allows.

This matches the operator's load-bearing constraint
([[user_non_technical_role]]: tools BUILT FOR the operator must be
no-code).  The Track A improvements primarily benefit Claude's own
loop discipline; Track B improvements benefit the operator's daily
experience.

**Recommended ship order** (per panel signal):

  W8-STOP-HOOK         (already shipped in this commit)
  W8-AUDIT-PROMPT      (already shipped in this commit)
  W8-PREFLIGHT-FIX     ⭐⭐⭐ — kill the #1 readiness blocker
  W8-OPERATOR-RUNBOOK  ⭐⭐⭐ — give the operator a daily playbook
  W8-STATUS-HUMAN      ⭐⭐ — plain-language daily pulse
  W8-ENGINES-HEAL      ⭐⭐ — one-command engine recovery
  W8-MUTATION-CANARY   ⭐ — Track A continuation
  W8-OBSERVER-DASHBOARD ⭐ — Track A continuation
  W8-TRANSPORT-REDUNDANCY ⭐ — Track A continuation
  W8-CLOSEOUT          — wave closeout + re-audit

Final operator decision pending: SHIP Track B first, or stay with the
original Track A theme?
