# Wave 8 closeout — Detection layer + operator-readiness foundation

**Authored**: 2026-05-24 by Claude after shipping the Wave 8 backlog under autonomous-loop discipline.

**Driver recap**: Wave 7 ended with all 8 rows shipped, no audit STOPs, and 1544 passing tests.  Two 10-reviewer panels (the W7 interaction panel + the W8 readiness panel) framed Wave 8 around two complementary themes:

- **Track A — Detection layer** (interaction-panel synthesis): tighten the audit gate, kill the stop-hook noise, and add mutation-canary so regressions can't slip in silently.
- **Track B — Operator readiness** (readiness-panel synthesis): zero of 10 reviewers voted YES to handing the harness to a non-technical operator today.  Convergent blockers: no `preflight --fix`, no operator runbook, no `status --human`, no `engines heal`.

Operator chose Track B as the primary W8 theme + a tighter Track A as warm-ups.

## What shipped (commit refs)

| Row | Status | Effort | Commit | Notes |
|---|---|---|---|---|
| W8-STOP-HOOK | shipped | ~30 min | `9aea866` + `7081d93` | Three-layer noise reduction (content-hash via git + 5-min debounce + extended path exclusions). Follow-through added the actual mutation-target-module exclusions the original comment claimed. |
| W8-AUDIT-PROMPT | shipped | ~15 min | `9aea866` + `083a1bf` | Diff cap 16K→48K; per-file budget 3K→8K; file cap 4→10; head+tail (60/40) strategy for truncation.  Re-audit of the 4 W7 STOPs all lifted to PASS. |
| W8-PLAN | shipped | ~45 min | `9aea866` | Two-track plan authored after both panels surfaced convergent themes. |
| W8-PREFLIGHT-FIX | shipped | ~75 min | `3dc8593` + `7081d93` | 3 fix functions (git_clean, pytest_cache, dead_engines) + run_fixes + FixOutcome.  Follow-through wired the W6-C2 L4 toast emission + EngineHealth schema fix (was silently failing every quarantine). |
| W8-OPERATOR-RUNBOOK | shipped | ~30 min | `6fbece0` + `7081d93` | Single-page playbook; non-technical operator can ship a day without writing Python.  Follow-through linked `engines heal` under the dead-engines recovery section. |
| W8-STATUS-HUMAN | shipped | ~45 min | `6fbece0` + `7081d93` | `harness today` (+ `harness today --since-hours N`) plain-language daily pulse.  Follow-through added `harness status human` alias per spec. |
| W8-ENGINES-HEAL | shipped | ~45 min | `6fbece0` + `7081d93` | `harness engines-heal` + `harness engines heal` subcommand alias.  Walks dead-engine alarm + engine_health, quarantines new-dead, marks already-quarantined+key-present as `recovering`, surfaces `blocked` when key absent. |
| W8-AUDIT-FOLLOWUP | shipped | ~90 min | `7081d93` | Schema + 6 audit STOPs addressed (see below). |

**8 of 8 backlog items shipped** + 1 follow-through commit to address the audit-gate STOPs.

## Schema bug discovered + fixed (load-bearing)

The W8 audit sweep surfaced a quarantine flow that **silently failed every write to engine_health**.  `EngineHealth.status` was `Literal["up","degraded","down"]` and Pydantic rejected the `quarantined`/`recovering` writes — but the fix functions caught the exception with `except Exception: continue`, so the error never surfaced.

`harness preflight --fix` would print `[FIXED] dead_engines` but the next preflight would show the same dead engines.  Same bug in `harness engines-heal`.

The follow-through commit (`7081d93`):
- Extended the Literal to include `quarantined` and `recovering`
- Added `last_quarantine` + `last_heal_attempt` ISO timestamp fields
- Updated `_check_dead_engines` to exclude already-quarantined/recovering engines (so the warning actually clears after `--fix`)
- Fixed the engines-heal `quarantined_now` set to handle both dict (test stubs) AND Pydantic forms (production read_engine_health)

Manual verification: `harness preflight --fix --skip-engines` now quarantines `anthropic` + `gemini`, fires the L4 toast for each, and subsequent preflight reports `[OK] dead_engines    all engines below failure threshold`.  The flow was broken before the fix; it works now.

## Audit roll-up — W8 sweep

The MiMo audit sweep on the original W8 commits (before the follow-through) returned 6 STOP + 5 PASS.  Categorisation:

| Category | Audits | Action |
|---|---|---|
| Legitimate criteria gap | 3 (W8-ENGINES-HEAL, W8-PREFLIGHT-FIX, W8-STATUS-HUMAN) | Fixed in follow-through commit `7081d93` |
| Audit-script artifact / mis-read | 2 (W8-AUDIT-PROMPT, W8-STOP-HOOK) | W8-AUDIT-PROMPT anchor moved to the re-audit commit; W8-STOP-HOOK find-exclusion gap also fixed |
| Spurious nondeterminism | 1 (W7-MUTATION-ORCH dropped 0.72 → 0.40 on the second pass at the same commit) | Same code, same auditor, different output.  MiMo non-determinism — accepted as shipped per W6-PANEL precedent. |

Re-audit results pending the in-flight sweep against the follow-through commit; expect each legitimate-gap row to lift to PASS (≥0.7) now that the criteria are met.

## What this wave doesn't ship

Track A's larger items deferred to Wave 9:

- **W8-MUTATION-CANARY** — 3-mutant rolling spot-check (deferred; no regressions seen this wave so the gate's not load-bearing yet)
- **W8-PROXY-MUTATION-KILL + observer + loops + dashboard** — only if canary finds 0-rate (deferred with the canary)
- **W8-OBSERVER-DASHBOARD** — queryable surface for observer logs (deferred)
- **W8-TRANSPORT-REDUNDANCY** — SSE-drop fallback (deferred)

Wave 9 candidates queued in STATUS.csv.

## Operator-readiness delta

The W8 readiness panel (5 MiMo + 5 Kimi) gave 0/10 YES at the start of W8.  Track B addressed each convergent blocker:

| Blocker (votes) | Address | Now |
|---|---|---|
| No `preflight --fix` (8/10) | W8-PREFLIGHT-FIX | Three auto-remediations + dry-run + reversal-path messaging |
| No operator runbook (6/10) | W8-OPERATOR-RUNBOOK | Single-page playbook; README BOLD callout |
| No `status --human` (5/10) | W8-STATUS-HUMAN | `harness today` + `harness status human` |
| No `engines heal` (4/10) | W8-ENGINES-HEAL | `harness engines heal` (subcommand) + `harness engines-heal` (top-level) |

Re-running the readiness panel against the post-Track-B state is the next session's first action — expect the YES vote count to move above 0, but the panel's job is to find what's still missing.  This closeout does not pre-judge that result.

## Loop discipline this wave

- 1571 tests pass + 6 skip (W7 close: 1544 pass + 6 skip; net +27)
- MiMo audit gate fired before each major commit landed (or shortly after, per W7-AUDIT-POLICY)
- STATUS.csv updated on every task transition (`feedback_status_csv_canonical.md`)
- Stop-hook noise went from ~6 fires/session to ~0 fires/session after W8-STOP-HOOK
- No L5 escalations
- Wave completed in one autonomous arc (no operator nudging mid-wave)

## Pending for the operator's next session

1. **Re-run readiness panel** against the post-Track-B state.  Expected: YES count above 0; new blockers surface for Wave 9.
2. **Re-run the W8 audit sweep** against `7081d93` to capture the post-follow-through audit numbers in this closeout (currently in-flight at the time this doc landed).
3. **Pop the second auto-stash** if you have anything you want back: `git stash list` shows one residual stash from an earlier `--fix` test.  Inspect with `git stash show stash@{0}` before popping.

— End of closeout —
