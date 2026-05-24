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

State at HEAD (commit 6160a4f, pushed to origin/master):
  - Wave 8 shipped + closed: 8/8 backlog rows + 1 closeout doc
  - 1576 tests pass + 6 skip
  - 14 Wave 9 rows queued in coord/STATUS.csv (grep '^W9-')
  - Master audit returned 0/40 SHIP-AS-IS, 10/40 HOLD, 30/40 SHIP-WITH-FIXES

You have FULL DEV AUTHORITY (memory: feedback_xaxiu_harness_full_dev_authority).
Commit, push, dispatch, install deps without asking. Only L5 errors escalate.
Run until the W9 queue empties, NOT until one row ships
(memory: feedback_full_automation_until_wave_plan_empty).
No permission-seeking; pick + execute (memory: feedback_no_permission_seeking).

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
  4. Move to W9-MUTATION-CANARY
  5. Continue until the W9 queue is empty

Do NOT ask "should I proceed?" — proceed.
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
