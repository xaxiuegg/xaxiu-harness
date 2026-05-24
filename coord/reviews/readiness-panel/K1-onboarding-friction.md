<!-- name=K1-onboarding-friction latency_ms=93391 error='' -->

## Rubric

1. **Install** — 2. Doc triad splits authority; operator faces conflicting gates (`doctor` OK vs `preflight` fail) and an unguided sequence of ≥5 decisions (which doc? `doctor`/`install`/`init`? fix `git_clean`? UNSET keys okay? brief now?). Non-technical users cannot self-remediate untracked-file failures.

2. **Daily run** — 3. `morning-brief` is buried in a 30-verb CLI with no daily alias or checklist, forcing the operator to remember the exact incantation amid irrelevant commands.

3. **Observe** — 4. STATUS.csv is readable; `dashboard-serve` and `observer` surfaces are usable without opening `runs/`. Engine root-cause still requires log literacy, but the panel is viable.

4. **Recover** — 2. `engines-heal` covers engine death, but preflight false-positives and proxy failures lack operator-visible remediation; the `git_clean` warn→fail path has no CLI fix.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The operator can read STATUS.csv and run CLI commands, but the first-run experience forces a high-stakes doc choice and a preflight git failure they cannot self-resolve. Once past the wall, daily observation is viable; recovery from non-engine failures is not.

6. **Top 3 blockers**
   - **`GETTING_STARTED.md`** prescribing exact first-run sequence and explicitly excluding CLAUDE.md/SESSION_BOOTSTRAP.md from operator scope.
   - **`harness preflight --operator`** (or profile-aware default) that suppresses `git_clean` blockers and explains fixes in plain language.
   - **`harness day-start`** meta-command wrapping `preflight` + `morning-brief` + `observer status` into one daily report to eliminate decision fatigue.
