<!-- name=M3-error-recovery latency_ms=29256 error='' -->

## Rubric

1. **Install** — **4/5.** `doctor` and `preflight` are clean, one-command gates. But the `git_clean` fail says "Commit or stash" without the exact command — a non-technical operator will stall here and have to escalate. Needs `git stash` copy-paste guidance inline.

2. **Daily run** — **4/5.** `harness morning-brief` + `harness daily` exist; loop start hint is explicit. The observer warning ("will retry next preflight") means the operator just re-runs — acceptable. Minor toil: if re-run also times out, there's no second-step guidance.

3. **Observe** — **3/5.** STATUS.csv is scannable, `dashboard-serve` exists, `heartbeat` is listed. But we see no evidence the dashboard surfaces engine health, escalation history, or loop status in non-technical language. The 310-row CSV is the primary observability surface — that's a raw file, not an operator experience.

4. **Recover** — **3/5.** `engines-heal` is a strong verb for the most common failure. Preflight gives "Run to fix:" hints, which is the right pattern. But two gaps: (a) the L5 escalation contract has no visible output template — when an L5 fires, what does the operator *see* and *do*? Unknown. (b) Observer timeout → "re-run or check scheduler-status" — if the scheduler itself is broken, the operator is dead with no next step.

5. **Hand to non-technical operator today?** **WITH GUARDRAILS.** The CLI verbs and preflight hints are 80% there. A non-technical operator can install, run daily, and recover from dead engines. But the `git_clean` blocker has no copy-paste fix, L5 escalation behavior is undocumented in the snapshot, and observability requires reading raw CSV. With a short runbook covering those three gaps, this is hand-offable within a day.

6. **Top 3 blockers**
   - **`git_clean` remediation is not copy-pasteable.** Preflight should print `git stash` or auto-stash with `--fix` flag. Single biggest blocker for non-technical operator.
   - **No L5 escalation output contract visible.** Operator needs to see what an L5 surface looks like and what the single action is. Without this, autonomous mode is a black box on hard failures.
   - **Observer has no second-tier recovery path.** If `observer scheduler-status` also fails, the operator needs `engines-heal`-style one-command recovery or a clear "file this" packet — neither is present.
