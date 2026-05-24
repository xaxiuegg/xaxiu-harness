# Session handoff — 2026-05-24 → Wave 9 kickoff

**Copy-paste the "Master prompt" block below into the next session's first message.**

---

## Master prompt (paste this verbatim)

```
You are resuming xaxiu-harness work at D:\xaxiu-harness-standalone\ (NOT warehouse).
Read CLAUDE.md + memory + these three docs IN ORDER:

  1. coord/SESSION_HANDOFF_2026-05-24.md     (this file — what + why)
  2. coord/reviews/master-audit/OPERATOR_SUMMARY.md  (40-reviewer findings)
  3. coord/reviews/wave-8-closeout.md         (last wave's state)

State at HEAD (commit cbb589b, pushed to origin/master):
  - Wave 8 shipped + closed: 8/8 backlog rows + 1 closeout doc
  - 1576 tests pass + 6 skip
  - 14 Wave 9 rows queued in coord/STATUS.csv (grep '^W9-')
  - Master audit returned 0/40 SHIP-AS-IS, 10/40 HOLD, 30/40 SHIP-WITH-FIXES

You have FULL DEV AUTHORITY (memory: feedback_xaxiu_harness_full_dev_authority).
Commit, push, dispatch, install deps without asking. Only L5 errors escalate.
Run until the W9 queue empties, NOT until one row ships
(memory: feedback_full_automation_until_wave_plan_empty).
No permission-seeking; pick + execute (memory: feedback_no_permission_seeking).

═══════════════════════════════════════════════════════════════════════
AUTONOMOUS LOOP — keep firing until W9 queue is empty
═══════════════════════════════════════════════════════════════════════

This session is an autonomous loop, not a single Q&A.  Loop discipline:

(a) PARALLELIZE.  At every decision point, ask "can I dispatch this
    to Kimi/DeepSeek and keep working on something else?"  Default
    YES unless the next step strictly depends on the current output.
    Existing patterns: scripts/run_*_panel.py for fan-out, background
    Bash tool runs for long ops, multi-packet xaxiu-swarm for multi-
    file refactors.

(b) BACKGROUND + WAKEUP.  When you fire a long-running dispatch / audit
    / panel run (anything >30s), use run_in_background=true on the
    Bash call.  When the only thing left to do is wait, call
    ScheduleWakeup with delaySeconds=1200 (20min) and prompt set to
    THIS SAME master-prompt text — the wakeup re-invokes you with the
    full context.  Don't poll; the harness notifies you when bg work
    finishes.

(c) NO PREMATURE STOP.  Before any "session is done" / "natural pause"
    reply, run `harness session ok-to-stop` (memory:
    feedback_no_premature_stop).  Exit 1 means keep working.
    Acceptable stop conditions are ONLY:
      - `grep '^W9-' coord/STATUS.csv | grep -v shipped` returns empty
      - An L5 error (key revoked, git auth dead, DPAPI unreadable)
      - Operator explicitly types a new directive
    "I shipped one row" is NOT a stop condition.

(d) AUDIT-IN-LOOP.  After each W9 row ships, fire its MiMo audit AND
    immediately pick the next row.  Don't wait for the audit verdict
    before starting the next row — the audit runs in parallel.  Only
    block on the audit if it returns persistent STOP across 3 runs
    (which is why W9-AUDIT-NONDETERMINISM-AVG is row #1).

(e) FAN-OUT FOR UNCERTAINTY.  When uncertain about an approach (memory:
    feedback_operator_inputs_become_harness_config last paragraph),
    dispatch 2-3 Kimi packets with alternative framings rather than
    agonizing alone.  scripts/run_*_panel.py shows the pattern.

(f) STOP-HOOK NOISE TOLERANCE.  Hooks fire spuriously sometimes (CRLF
    false-positive + mtime drift).  After 2 hook fires with no real
    staleness, stop responding to them with single-char replies
    (memory: feedback_never_silent_on_hook_loops).  Either execute a
    pending directive or state plainly "halting until real input"
    — never a bare `.`.

(g) WAVE 9 EXIT CONDITION.  When all 14 W9 rows show `Status=shipped`
    in coord/STATUS.csv, author coord/reviews/wave-9-closeout.md +
    queue Wave 10 candidates from any new findings + run a final
    audit sweep.  Only THEN is the loop allowed to exit cleanly.

Your W9 priority is the panel's composite vote, ship in this order:

  1. W9-AUDIT-NONDETERMINISM-AVG  — --avg-of-N on the audit gate.
                                     Every later verdict depends on this.
  2. W9-MUTATION-CANARY            — deterministic regression signal
                                     that bypasses MiMo entirely.
  3. PARALLEL:
     - W9-CLI-TIMEOUT-BUDGET       — perf-regression test + graceful
                                     degrade on preflight / today.
     - W9-PREFLIGHT-FIX-NOSTASH    — kill the silent stash data-loss
                                     surprise in `preflight --fix`.
  4. W9-SILENT-EXCEPTION-AUDIT     — grep `except .* continue` across
                                     engines/ + dispatch/ + state/;
                                     convert each to logger.warning(exc)
                                     at minimum, or surface via L4 alarm.
  5. W9-READINESS-PANEL-RERUN      — re-run scripts/run_readiness_panel.py
                                     and measure delta vs W8 baseline 0/10.

After those 5 ship, work the rest of the W9 queue in any order:
  W9-AUDIT-ANCHOR-MULTI-COMMIT
  W9-STATE-ATOMIC-WRITES
  W9-STATE-FILE-LOCK
  W9-REDACTION-INTEGRITY-TEST
  W9-PROXY-FAILURE-MATRIX
  W9-MUTATION-MANIFEST
  W9-ONCOMMIT-HOOK-CRLF

Standing constraints:
  - Run scripts/audit_task_with_mimo.py <row-id> --commit <sha> after each
    row ships. ≥0.7 = PASS, <0.7 = STOP (but trust the average — single
    runs are non-deterministic, that's W9 row #1's whole point).
  - STATUS.csv updates on every transition (start / complete / defer).
  - Don't touch warehouse files or its STATUS.csv.
  - Stop-hook noise: don't chase mtime drift. The hook fires falsely
    sometimes (W9-ONCOMMIT-HOOK-CRLF + CRLF anchor bug).
  - `harness preflight --fix` AUTO-STASHES dirty work. If your edits
    vanish after running it, recover via `git stash pop`. Fixing this
    behavior IS one of the W9 rows.

Tooling notes:
  - Engine dispatch: `xaxiu-swarm dispatch --backend kimi/kimi-api/deepseek`
  - Kimi for non-V-file work, DeepSeek for V-file/math/ship-critical,
    Claude in-session only (memory: feedback_engine_routing_2026_05_11).
  - Run pytest with: PYTHONPATH=src python -X utf8 -m pytest tests/ -q
  - Panel runs work; existing examples in scripts/run_*_panel.py

Boot sequence for this session:
  1. git status; git log --oneline -5     (verify state)
  2. Read the 3 docs above
  3. Start W9-AUDIT-NONDETERMINISM-AVG — design the --avg-of-N flag in
     scripts/audit_task_with_mimo.py; ship + commit + push + mark
     STATUS.csv shipped + audit the audit-change itself
  4. While the audit runs in background, START W9-MUTATION-CANARY in
     foreground — don't wait for audit result before next row
  5. After each row ships, immediately scan `grep '^W9-' coord/STATUS.csv |
     grep -v shipped` — if non-empty, pick next.  Don't break the loop.
  6. When ALL W9 rows show shipped, write coord/reviews/wave-9-closeout.md
     and run the final master-audit sweep.  THEN run
     `harness session ok-to-stop`.  Only exit 0 ends the loop.

Loop re-entry (if context window pressures force a wakeup):
  - Call ScheduleWakeup(delaySeconds=1200, prompt=THIS_MASTER_PROMPT,
    reason="Wave 9 loop continuation")
  - Background work notifies you automatically; don't poll.

Do NOT ask "should I proceed?" — proceed.
Do NOT stop after one row — the wave is 14 rows.
Do NOT silent-loop on hook noise — execute or state halt plainly.
```

---

## What this doc replaces (so you don't re-read)

If you need any of these, they're in the repo — skip otherwise:

- The full master audit (`coord/reviews/master-audit/SYNTHESIS.md`) is 800 lines of per-persona detail; `OPERATOR_SUMMARY.md` is the 5-minute synthesis.
- The W8 closeout (`coord/reviews/wave-8-closeout.md`) has the 3-sweep audit history; the master audit incorporates its findings.
- STATUS.csv tail has every shipped row; `grep '^W9-' coord/STATUS.csv` shows just the next-wave queue.

## What's NOT in scope for the next session (deferred)

- The W6/W7 PASSes don't need re-audit; they're shipped.
- The 2 persistent-STOP W8 rows (W8-STOP-HOOK, W8-AUDIT-PROMPT) are accepted-as-shipped per the W6-PANEL precedent. Don't re-litigate.
- Track A leftovers from W8 (W8-OBSERVER-DASHBOARD, W8-TRANSPORT-REDUNDANCY) — deferred indefinitely unless a panel re-surfaces them.

## Known stale stash

There's one residual `git stash list` entry from a `--fix` test earlier:

```
stash@{0}: On master: harness preflight --fix auto-stash 2026-05-24T02:44:31...
```

It was retained because I couldn't tell what work it captured. Inspect with `git stash show stash@{0}` before popping; if it's just an earlier copy of files now committed, `git stash drop stash@{0}` is safe.

## Hook gotchas

- `.claude/hooks/check-csv-stale.sh` — fires at end-of-turn if STATUS.csv mtime is older than other recent edits. After W8 work it's much quieter, but expect ~0-1 fire per session. Treat as noise unless STATUS.csv genuinely wasn't updated.
- `.claude/hooks/check-csv-on-commit.sh` — fires when a commit "doesn't touch STATUS.csv". Has the CRLF false-positive bug (W9-ONCOMMIT-HOOK-CRLF). If you see it fire after a commit that clearly DID touch STATUS.csv, it's the CRLF bug — fixing it is itself a W9 row.

— End handoff —
