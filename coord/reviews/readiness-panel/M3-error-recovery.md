<!-- name=M3-error-recovery latency_ms=23769 error='' -->

## Rubric

1. **Install** — 3/5. Preflight exits with code 1 on a non-fatal warning (untracked files), which could confuse a non-technical operator who expects green=all clear.
2. **Daily run** — 4/5. The morning sequence (`doctor`, `preflight`, `morning-brief`) is clear and CLI-driven. Low toil.
3. **Observe** — 3/5. `status`, `heartbeat`, and `dashboard-serve` exist, but a typical failure (e.g., an engine timeout) isn't guaranteed to surface as a clear, actionable item in the dashboard without the operator knowing to run `engines-heal` or check logs.
4. **Recover** — 2/5. A Python traceback from an unexpected exception (e.g., a network blip causing a module error) would block the operator dead. They can't interpret it. The `engines-heal` and `panic-dump` commands are recovery tools, but the path *to* them from an opaque error is unclear.

5. **Hand to a non-technical operator today?** **WITH GUARDRAILS**. The operator can run the daily commands and use the dashboard for visibility. However, any failure that results in a raw Python exception will halt them. They need a "handle" for every common error type that avoids tracebacks and points to a CLI recovery command, or a reliable on-call Python-savvy backup.

6. **Top 3 blockers**:
   - **Standardize error surfacing.** All exceptions must be caught and rendered as a non-technical "operator packet" with a severity (e.g., `[L4]`), a plain-English summary, and a recommended CLI fix (e.g., `Run 'harness engines-heal --engine DeepSeek'`).
   - **Add a `harness recover` command.** A single entry point that runs a sequence of checks (`doctor`, `engines-heal`, `preflight`) and presents a pass/fail summary, giving the operator one command to try first.
   - **Make the escalation threshold contract explicit in output.** The `--escalation-threshold` setting should be printed in the `doctor` or `preflight` header so the operator knows what level of issue will surface vs. be silently handled.
