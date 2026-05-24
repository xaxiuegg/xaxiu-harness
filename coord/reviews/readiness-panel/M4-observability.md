<!-- name=M4-observability latency_ms=16042 error='' -->

## Rubric
1. **Install — 2/5** — Preflight fails (dead engines, test failures) requiring Python/git debugging beyond YAML/CLI skills.
2. **Daily run — 4/5** — `dashboard-serve`, `morning-brief`, and `heartbeat` exist; sequence is logical if preflight is green.
3. **Observe — 3/5** — STATUS.csv, dashboard, and observer flags are good surfaces, but engine health and test failures require inspecting `state/` logs.
4. **Recover — 2/5** — Remediation hints exist in `doctor`/`preflight` output but require understanding "rotate keys," "fix failures," or reading `lastfailed`.

## 5. Hand to a non-technical operator today? **NO**
The harness has strong observability surfaces (STATUS.csv, dashboard, observer flags) and the CLI is well-structured for a non-technical operator. However, the current snapshot shows actionable blockers—dead engines and test failures—that the operator cannot resolve with their allowed skills (YAML edits, CLI commands, Task Scheduler). The remediation messages ("rotate keys," "run pytest, fix failures") are too vague for someone who cannot read logs or author Python. Without first clearing these blockers and ensuring `harness preflight` passes green, handing this over would leave the operator stuck on day one.

## 6. Top 3 blockers
1. **Dead engines** — Provide a one-command `harness engines-quarantine` or key-rotation wizard that the operator can run without inspecting `state/` files.
2. **Test failures** — Either auto-fix or surface a clear "acknowledge and skip" path for the operator, since they cannot debug pytest.
3. **Preflight verbosity** — Transform "modified tracked files" and "last run had failures" into guided CLI flows (e.g., `harness preflight --fix`) that handle or explain each issue interactively.
