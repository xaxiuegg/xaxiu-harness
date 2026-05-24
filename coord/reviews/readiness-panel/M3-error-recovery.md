<!-- name=M3-error-recovery latency_ms=18941 error='' -->

## Rubric

1. **Install** — 2/5 — Preflight fails on `dead_engines` and `git_clean`. Fix for dead engines points to a JSONL log the operator cannot parse. Git fix is clear (`git stash`). Preflight is a blocker gate, so a fresh clone would not go green.
2. **Daily run** — 3/5 — `harness morning-brief` is obvious. However, preflight (likely a morning prerequisite) will fail until the operator resolves technical issues, which is not low-toil.
3. **Observe** — 5/5 — STATUS.csv, dashboard, and CLI (`status`, `heartbeat`) provide full visibility without needing to read raw files or logs.
4. **Recover** — 1/5 — Critical failure: `pytest_cache` fix says "Run pytest, fix failures, then retry." The operator cannot debug or fix Python test failures. This blocks them dead. The `dead_engines` fix also requires reading a performance log and potentially rotating API keys—a technical task.

5. **Hand to a non-technical operator today?** NO.
The operator would be immediately blocked by the `pytest_cache` preflight failure. The remediation path ("fix failures") requires Python debugging, which is outside their capabilities. Without a single command to reset or clear this state (e.g., `harness preflight --clear-failures`), the harness is unusable for them.

6. **Top 3 blockers**
    1. **`pytest_cache` failure remediation** — Needs a `harness fix tests` command that runs tests and either clears the cache on pass or presents a non-technical-friendly summary on failure.
    2. **`dead_engines` remediation** — Needs `harness engines quarantine <engine>` or a clear CLI command to rotate/reload keys, hiding the JSONL log.
    3. **Escalation contract for L5 (Python bugs)** — Need a concrete `harness panic-dump` + support-send workflow so the operator knows exactly what to do (e.g., "run `harness support send`") when a Python traceback surfaces, rather than just seeing an error.
