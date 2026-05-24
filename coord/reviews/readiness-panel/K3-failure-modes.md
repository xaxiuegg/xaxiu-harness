<!-- name=K3-failure-modes latency_ms=121756 error='' -->

## Rubric
1. **Install** — 2. Preflight fails on pytest cache and git state, and dead-engine remediation requires inspecting JSONL; a non-technical user cannot reach green unassisted.
2. **Daily run** — 3. `morning-brief` and `heartbeat` exist, but no single obvious daily checklist is surfaced; operators must juggle verbs and flags.
3. **Observe** — 3. STATUS.csv is readable, yet engine health and loop diagnostics still push operators toward JSONL/logs rather than a self-service dashboard.
4. **Recover** — 2. Preflight prints "fix:" hints, but every common failure routes to actions (pytest, git, JSONL) a non-technical operator cannot execute alone.

**Failure modes (first month)**
- **Dead engines** — Error clear (`[!] dead_engines`); recovery ("inspect JSONL / quarantine") is opaque → **ping engineering**.
- **Pytest cache blocking autonomy** — Error clear (`[X] pytest_cache`); recovery ("Run pytest, fix failures") requires coding → **ping engineering**.
- **Git dirty state** — Error clear (`[X] git_clean`); recovery ("Commit or stash") is borderline for a non-technical user → **likely ping engineering**.
- **Silent missing API keys** — Error unclear (`doctor` shows UNSET keys but overall OK); failure surfaces later with no obvious recovery → **ping engineering**.
- **Mid-loop routing failure** — Error unclear (buried in `runs/` files); no CLI recovery path → **ping engineering**.

**Hand to a non-technical operator today?** WITH GUARDRAILS. The daily verbs and STATUS.csv are accessible, but nearly every preflight failure mode routes to technical remediation the operator cannot execute alone. They can run the harness only if an engineer pre-clears the environment and stands by for escalations during the first month.

**Top 3 blockers**
- `harness preflight --fix` flag to auto-stash git, reset pytest cache, and quarantine dead engines.
- `harness operator-report` command translating every `[X]`/`[!]` into plain-language, copy-paste Windows/Task Scheduler instructions.
- `docs/OPERATOR_RUNBOOK.md` with exact non-technical remediation steps and screenshots for each preflight failure.
