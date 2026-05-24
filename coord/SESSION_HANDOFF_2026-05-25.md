# Session handoff — 2026-05-25 → Wave 10 kickoff

**Copy-paste the "Master prompt" block below into the next session's first message.**

---

## Master prompt (paste this verbatim)

```
You are resuming xaxiu-harness work at D:\xaxiu-harness-standalone\ (NOT warehouse).
Read CLAUDE.md + memory + these three docs IN ORDER:

  1. coord/SESSION_HANDOFF_2026-05-25.md     (this file — what + why)
  2. coord/reviews/wave-9-closeout.md         (W9 ship report + audit roll-up)
  3. coord/reviews/master-audit/OPERATOR_SUMMARY.md  (W8 baseline — re-read if a
     fresh master-audit landed; otherwise the W9 closeout's W10 candidates
     section is the authoritative starting backlog)

State at HEAD (commit bad66c1, pushed to origin/master):
  - Wave 9 shipped + closed: 14/14 backlog rows + 1 closeout doc + 1 final audit
  - 1745 tests pass + 6 skip + 3 slow tests deselected by default (run with `pytest -m slow`)
  - 10 Wave 10 rows queued in coord/STATUS.csv (grep '^W10-')
  - Readiness panel re-run: still 0/10 YES (9 WITH GUARDRAILS, 1 NO) — the
    YES bar is what W10 must move

You have FULL DEV AUTHORITY (memory: feedback_xaxiu_harness_full_dev_authority).
Commit, push, dispatch, install deps without asking. Only L5 errors escalate.
Run until the W10 queue empties, NOT until one row ships
(memory: feedback_full_automation_until_wave_plan_empty).
No permission-seeking; pick + execute (memory: feedback_no_permission_seeking).

═══════════════════════════════════════════════════════════════════════
AUTONOMOUS LOOP — keep firing until W10 queue is empty
═══════════════════════════════════════════════════════════════════════

Same loop discipline as the W9 prompt (a-g).  Key points:

(a) PARALLELIZE.  Dispatch to Kimi/DeepSeek if the next step doesn't
    depend on the current output.

(b) BACKGROUND + WAKEUP.  Use run_in_background=true on any Bash >30s.
    ScheduleWakeup with delaySeconds=1200 if there's literally nothing
    else to do, but the harness notifies on bg completion — don't poll.

(c) NO PREMATURE STOP.  Acceptable stop conditions:
      - `grep '^W10-' coord/STATUS.csv | grep -v shipped` returns empty
      - L5 error
      - Operator types a new directive

(d) AUDIT-IN-LOOP.  After each W10 row ships, fire its MiMo audit
    (`scripts/audit_task_with_mimo.py W10-FOO --commit <sha> --avg-of-N 3`)
    and immediately pick the next row.  Don't block on the audit verdict.

(e) FAN-OUT FOR UNCERTAINTY.  If unsure, dispatch 2-3 Kimi packets with
    alternative framings.

(f) STOP-HOOK NOISE.  W9-ONCOMMIT-HOOK-CRLF fixed the CRLF bug; the hook
    should fire much less often now.  Stop-hook tolerance still applies.

(g) WAVE 10 EXIT CONDITION.  When all 10 W10 rows show Status=shipped,
    author coord/reviews/wave-10-closeout.md + queue Wave 11 candidates
    from any new findings + re-run the readiness panel.  Only THEN can
    the loop exit cleanly.

Wave 10 theme: operator-readiness UX.  The W9 readiness panel re-run
returned 0/10 YES; the convergent blockers are all UX-side, not
correctness-side.  Composite-vote shipping order:

  1. W10-PREFLIGHT-EXIT-CODE-SEMANTICS  — splits warn (exit 1, actionable)
                                          from fail (exit 2+, blocker).
                                          Every operator-facing command
                                          downstream benefits.
  2. W10-DAILY-QUICKSTART-VERB           — `harness daily` sequences the
                                          4-step morning routine + hides
                                          advanced flags.
  3. W10-PREFLIGHT-REMEDIATION-CARDS     — surface the exact `fix:` verb
                                          directly under each warning so
                                          the operator doesn't dig.
  4. W10-PROFILE-AWARE-DEFAULTS          — set --profile non_technical
                                          once + persist; default for the
                                          operator's home dir.
  5. W10-STATUS-CSV-OVERWHELM            — `harness status --recent 20`
                                          surfaces the present without
                                          dropping history.
  6. W10-ENV-VAR-WIZARD                  — `harness install` walks
                                          through KIMI/DEEPSEEK/MIMO
                                          key population + DPAPI seed.
  7. W10-DPAPI-SEEDING-VISIBILITY        — runbook section explaining
                                          where keys come from + how to
                                          rotate them.

After those 7 UX rows ship, work the remaining 3 in any order:
  W10-FRESH-CANARY-MODULES          — pop the canary against the 3
                                       warm-tier modules with null SHA.
  W10-MIMO-FILTER-INVESTIGATION     — every W9 audit hit MiMo's content
                                       filter; either rephrase the prompt
                                       or accept DeepSeek as primary.
  W10-AUDIT-FOLLOWUP-COMMIT-POLICY  — followup commits inherit the
                                       original commit's verdict; add a
                                       `--reaudit` flag.

Standing constraints (same as W9):
  - `scripts/audit_task_with_mimo.py <row-id> --commit <sha> --avg-of-N 3`
    after each row.  Mean ≥0.7 = PASS, <0.7 = STOP (but trust the
    average — the avg-of-N IS designed to dampen MiMo noise).
  - STATUS.csv updates on every transition.
  - Don't touch warehouse files.
  - `harness preflight --fix` no longer auto-stashes by default
    (W9-PREFLIGHT-FIX-NOSTASH).  Pass `--allow-stash` if you want
    legacy behavior.

Tooling notes (same as W9):
  - Engine dispatch: `xaxiu-swarm dispatch --backend kimi/kimi-api/deepseek`
  - Default DeepSeek model: `deepseek-v4-flash` (5× cheaper than pro)
  - Run pytest with: `PYTHONPATH=src python -X utf8 -m pytest tests/ -q`
  - Run wall-clock tests with: `-m slow` (W9-CLI-TIMEOUT-BUDGET)
  - Canary: `PYTHONPATH=src python -X utf8 scripts/run_mutation_canary.py`
  - Master audit: `PYTHONPATH=src python -X utf8 scripts/run_master_audit_panel.py`
  - Readiness panel: `PYTHONPATH=src python -X utf8 scripts/run_readiness_panel.py`

Boot sequence:
  1. git status; git log --oneline -5
  2. Read the 3 docs above
  3. Start W10-PREFLIGHT-EXIT-CODE-SEMANTICS — the simplest exit-code
     split that unlocks the rest.  Ship + commit + push + mark
     STATUS.csv shipped + audit-in-background.
  4. Immediately START W10-DAILY-QUICKSTART-VERB in foreground.
  5. After each row ships, scan `grep '^W10-' coord/STATUS.csv |
     grep -v shipped`; if non-empty, pick next.
  6. When ALL W10 rows shipped, write coord/reviews/wave-10-closeout.md,
     re-run the readiness panel (4th time — track the YES delta over
     time), queue Wave 11 candidates, fire final master audit, then
     `harness session ok-to-stop`.

Loop re-entry: ScheduleWakeup(delaySeconds=1200, prompt=THIS_MASTER_PROMPT,
reason="Wave 10 loop continuation") — only if context pressure forces it.

Do NOT ask "should I proceed?" — proceed.
Do NOT stop after one row — the wave is 10 rows.
Do NOT silent-loop on hook noise.
```

---

## What this doc replaces (so you don't re-read)

- The full master audit (post-W9) lives at `coord/reviews/master-audit/`
  if it landed; the W9 closeout's "Wave 10 candidates" section is the
  authoritative starting backlog regardless.
- The W9 closeout (`coord/reviews/wave-9-closeout.md`) has the audit
  roll-up + the readiness-panel delta + the W10 candidate list.

## What's NOT in scope for the next session (deferred)

- The 2 W9 STOPs that were addressed via followup commit `34c97bd`
  (W9-CLI-TIMEOUT-BUDGET + W9-SILENT-EXCEPTION-AUDIT) — if a reviewer
  re-surfaces them, re-audit at `34c97bd`, not the original commit.
- W6/W7/W8 PASSes — shipped, don't re-litigate.

## Known footguns

- `preflight --fix` no longer silently stashes — if the operator's
  habit is to expect a stash, the new message explicitly names
  modified files + the `--allow-stash` flag.
- Wall-clock tests in `tests/test_perf_budget.py` are marked `@pytest.mark.slow`
  and deselected by default.  Run with `-m slow` to exercise.
- The mutation canary rotates state in `coord/canary_state.json`.
  Don't `--module` override unless you want to break the rotation.
- MiMo's content filter rejected every W9 audit (~60s per attempt
  before DeepSeek fallback kicked in).  Budget accordingly — each
  audit takes ~2-3min wall-clock with the avg-of-N=3 flag.

— End handoff —
