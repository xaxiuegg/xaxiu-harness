<!-- name=K1-onboarding-friction latency_ms=120566 error='' -->

## Rubric

1. **Install** — 2. `doctor` reports OK while `preflight` hard-fails (exit 4) on dirty git, unregistered loop, and observer timeout; the 6+ remediation decisions (commit vs stash, loop start, observer retry vs scheduler check) exceed a non-technical operator's 30-minute runway.

2. **Daily run** — 3. `daily` and `morning-brief` are discoverable, but the CLI never signals that `install` → `env-wizard` → `loop start` → green `preflight` must precede them, forcing 6+ operator decisions before the first brief.

3. **Observe** — 4. `dashboard-serve`, `heartbeat`, `STATUS.csv`, and engine reliability commands give strong visibility without reading run files; only the observer probe timeout in preflight hints the observation layer may need a manual kick-start.

4. **Recover** — 3. `doctor`, `engines-heal`, and preflight fix-hints exist, but divergent advice (`doctor` OK vs `preflight` FAIL) and branching fixes (commit *or* stash; re-run *or* check scheduler) force decisions rather than a single obvious path.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The CLI surface is rich with diagnostics and wizards, yet the first-run path is blocked by a failing preflight that demands git operations and distributed-system intuition; an operator needs a human runbook or babysitter for the initial 30-minute bootstrap, after which daily verbs are manageable.

6. **Top 3 blockers**:
   - `harness onboard` quickstart artifact — one ordered checklist/script from clone to first `morning-brief` replacing guesswork.
   - `harness preflight --fix` — auto-stash dirty files, start the loop, and retry observer probe instead of printing branching options.
   - `harness observer bootstrap` — one-shot scheduler registration that eliminates the ambiguous timeout remediation.
