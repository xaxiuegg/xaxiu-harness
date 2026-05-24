<!-- name=K2-documentation latency_ms=106047 error='' -->

## Rubric

1. **Install** — **2**. `harness doctor` is readable, but `preflight` exits 1 on a cryptic `git_clean` warning with no remediation hint, and no simple first-run wizard output is shown.
2. **Daily run** — **2**. `morning-brief` and `dashboard-serve` suggest routine awareness, yet the CLI presents 20+ undifferentiated commands with no obvious daily sequence or plain-language “what do I run today?” guide.
3. **Observe** — **2**. Observer and dashboard primitives exist, but `STATUS.csv` is packed with ticket IDs, mutation metrics, and arcane module names; no evidence of a non-technical summary view.
4. **Recover** — **2**. `engines-heal` and `doctor` are discoverable, but preflight warnings lack remediation steps and `STATUS.csv` explicitly flags undocumented proxy failure modes and missing recovery matrices.

## Hand to a non-technical operator today?
**WITH GUARDRAILS.** A motivated operator could run pre-canned commands like `morning-brief` and `dashboard-serve` if a technical user performs initial setup, hides the full `--help` surface, and provides a 1-page cheat sheet. They cannot self-install or self-recover from warnings like `git_clean` or dead engines without a runbook.

## Top 3 blockers
- **Plain-language install runbook**: translate `preflight`/`doctor` outputs into “if you see X, do Y” steps.
- **Simplified daily operator view**: collapse the 20+ CLI verbs into an opinionated daily checklist (e.g., `harness today`) instead of requiring the operator to navigate subcommands.
- **Failure-mode recovery cards**: attach human-readable remediation to every `preflight` warning and `STATUS.csv` `todo` so the operator knows which single command to run next.
