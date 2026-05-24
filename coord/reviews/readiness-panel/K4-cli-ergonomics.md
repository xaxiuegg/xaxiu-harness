<!-- name=K4-cli-ergonomics latency_ms=105931 error='' -->

## Rubric

1. **Install — 3** `doctor` reads clearly, but `preflight` is missing from `--help`, exits 1 on `git_clean` without a remediation hint, and requires the operator to reason about untracked files.

2. **Daily run — 3** `morning-brief` exists, yet there is no single obvious daily entry-point; the operator must guess whether to run `loop`, `loops`, `coord`, or just read the dashboard.

3. **Observe — 4** Dashboard, observer, and STATUS.csv provide good visibility, but the CLI lacks a unified `harness today` summary that surfaces all three for a non-technical user.

4. **Recover — 3** `engines-heal` and `doctor` cover some failures, but common stale states (untracked files, routing locks) lack a one-step remediation verb such as `harness fix` or `harness unlock`.

5. **Hand to a non-technical operator today?** **WITH GUARDRAILS**. Installation and daily observation are possible, but the 60+ subcommand surface is overwhelming, verb naming is inconsistent (`loop` vs `loops`, hidden `preflight`), and recovery requires interpreting diagnostic badges rather than running a guided repair command. A printed runbook is mandatory.

6. **Top 3 blockers**
   - **`harness today` meta-command**: rolls up `preflight`, `observer`, and `coord status` into one daily operator summary.
   - **`harness tidy` / `preflight --fix`**: auto-remediate `git_clean`, lock drift, and stale caches without manual git commands.
   - **Discoverability fix for `preflight`**: surface it in `harness --help` and add a `--fix` flag so the readiness gate is findable and actionable.
