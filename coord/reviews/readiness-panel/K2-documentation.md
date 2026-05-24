<!-- name=K2-documentation latency_ms=102951 error='' -->

## Rubric

1. **Install** — 2. Preflight emits fixes, but "inspect JSONL" and "fix pytest failures" require dev skills; engine quarantine and test repair are not self-service for a non-coder.
2. **Daily run** — 3. `morning-brief` and `heartbeat` exist, yet the CLI lists 25+ verbs with no daily sequence spelled out; the operator must hunt for the right ones.
3. **Observe** — 4. `dashboard-serve`, `observer`, and STATUS.csv give visibility without opening `runs/`, but 269-row CSV lacks a plain-language summary for quick scanning.
4. **Recover** — 2. Failures surface clearly, yet remediation text points to JSONL logs, git stash, and pytest runs rather than simple CLI verbs or click-to-fix actions.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The CLI surfaces problems in plain English and offers `morning-brief`, but a non-technical operator cannot act on engine quarantine, pytest failures, or JSONL logs without assistance. They could run the daily loop if a technical owner handled initial setup and kept preflight green, but self-recovery is out of reach.

6. **Top 3 blockers:**
- `docs/operator-runbook.md` — one-page daily checklist (morning-brief → dashboard → observer) written for non-technical readers.
- `harness preflight --fix` — auto-remediates dead engines (auto-quarantine), dirty git (auto-stash), and stale pytest cache without Python knowledge.
- `harness status --today` — human-readable overnight summary replacing 269-row CSV archaeology.
