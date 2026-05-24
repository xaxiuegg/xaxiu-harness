<!-- name=M18-STATUS-CSV-DISCIPLINE latency_ms=42010 error='' -->

## Score

**1. Correctness — 3/5.** Task rows map accurately to shipped commits (W8 items cross-check against `7081d93` refs). But ~130 rows are timestamped dispatches (`2026-05-24T081155Z` style) masquerading as tasks — the CSV conflates a task tracker with a dispatch log.

**2. Robustness — 2/5.** No schema enforcement on note length (W10-AUDIT-FOLLOWUP-COMMIT-POLICY packs regex boundary specs into a tracker cell). No status lifecycle — every visible row is "shipped"; where are queued/blocked items from W9's "10 candidates queued"? No validation that a row is a real Wn task vs. an auto-dispatch.

**3. Operator-usability — 2/5.** 310 rows with notes containing Pydantic Literal extensions and `find_latest_commit_for_task` boundary rules. A non-technical operator can't scan this in 30 seconds. Ironically, `harness today` and `harness status human` have become the *real* tracking surface — the CSV is now an engineering dump pretending to be an operator tool.

**4. Test discipline — 3/5.** Preflight checks `status_csv` is writable + recently touched. The W9 on-commit hook catches CRLF. But zero tests validate note-length bounds, row-type discrimination (task vs. dispatch), or that Wave N rows actually appear before the wave closes. The tracker's own integrity is untested.

**5. Risk — 3/5.** Not a ship-blocker today. But with ~130 dispatch rows per wave and waves accelerating, the CSV hits 500+ by W12. Notes will never be pruned. The tracker is losing its canonical status — `harness today` already superseded it for operator queries. Risk is entropy, not failure.

**6. Top blocker.** Split STATUS.csv into `tasks.csv` (Wn rows only, note cap ~200 chars, enforced by on-commit hook) and `dispatch_log.csv` (auto-generated, no manual notes). This removes ~130 noise rows immediately, makes the tracker scannable, and restores one-pane truth. The W10 `harness status human` verb already pulls from the CSV — it could pull from the cleaner table.

**7. Verdict: SHIP-WITH-FIXES.** The harness works, the operator surface is usable, but the canonical tracker has drifted into combined task-tracker-plus-dispatch-log noise that no one can actually audit — which defeats its purpose as a tracking primitive.
