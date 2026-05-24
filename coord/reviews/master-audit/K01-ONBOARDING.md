<!-- name=K01-ONBOARDING latency_ms=72271 error='' -->

## Score

1. **Correctness — 2/5** — `env-wizard`, `--fix`, and the runbook exist, but no golden path is surfaced at clone time; the operator must independently discover docs/OPERATOR_RUNBOOK.md and learn about `--fix` after already failing.
2. **Robustness — 2/5** — Preflight fails hard (exit code 4, opaque jargon) on a fresh machine with missing API keys or an uninitialized DPAPI store, rather than auto-invoking the wizard or offering one-command recovery.
3. **Operator-usability — 2/5** — Thirty-plus CLI verbs in `--help` overwhelm first contact; a non-technical operator lacks a visible 3-step funnel and must hunt for the handful of commands that matter for day one.
4. **Test discipline — 2/5** — 1,576 unit tests pass, yet no CI job simulates a fresh Windows clone → first green `harness preflight` end-to-end, so onboarding bit-rot is invisible until a human attempts it.
5. **Risk — 4/5** — The fail-rate of a first unassisted attempt is likely 60–80%; operators will abandon before they find the buried runbook.

6. **Top blocker** — Add a root `README.md` with a literal copy-paste quickstart (or a `harness onboard` verb that chains dependency check → `env-wizard` → `preflight --fix`), collapsing the decision tree to one command.

7. **Verdict** — **SHIP-WITH-FIXES**: the operator primitives are real but undiscoverable; the first 60 seconds after clone still leaks non-technical users.
