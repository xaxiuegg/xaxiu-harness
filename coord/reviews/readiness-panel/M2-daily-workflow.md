<!-- name=M2-daily-workflow latency_ms=23869 error='' -->

## Rubric
1.  **Install: 3/5** — Guided `install` and `env-wizard` exist, but a non-technical operator must troubleshoot `preflight` failures (git clean, loop registration) without clear, single-command fixes.
2.  **Daily run: 4/5** — `morning-brief` is the right verb, but its utility is undermined by a `preflight` that fails on common issues (stale git state), forcing extra steps.
3.  **Observe: 4/5** — `morning-brief`, `doctor`, `preflight`, and STATUS.csv provide layered observability. The operator avoids digging in `runs/`, but must correlate multiple command outputs.
4.  **Recover: 4/5** — CLI outputs include actionable "Run to fix:" hints and a dashboard. Failure modes are logged, but recovery for observer timeouts is vague ("will retry").

5.  **Hand to a non-technical operator today?** **WITH GUARDRAILS.** The CLI is self-documenting enough for daily flow (`morning-brief`, `preflight`), and STATUS.csv is readable. However, a blocked `preflight` (as shown) requires manual intervention that assumes basic git literacy or a support channel, creating a dependency on technical backup.

6.  **Top 3 blockers**
    *   **A `harness preflight --autofix` command** to auto-stash git changes and register loops, moving install/observe from a 3→5.
    *   **A single `harness daily` subcommand** that chains `morning-brief` + `preflight` with a clear success/failure summary, reducing command recall burden.
    *   **An observer probe health-check in `doctor`** to proactively surface and fix the timeout warning, increasing recovery confidence from a 4→5.
