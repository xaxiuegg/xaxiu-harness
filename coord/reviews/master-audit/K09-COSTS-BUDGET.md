<!-- name=K09-COSTS-BUDGET latency_ms=40683 error='' -->

## Score

1. **Correctness** — 2 — `budget` verb exists but snapshot shows no per-session cost output or ledger validation; operator cannot answer "what did this session cost" in one command.
2. **Robustness** — 2 — No evidence ledger handles write failures or token-skew; the W8 EngineHealth silent-schema bug shows similar data paths can fail undetected.
3. **Operator-usability** — 1 — `harness today` surfaces zero cost data; non-technical operator has no runbook step for spend checks and no proven one-command cost query.
4. **Test discipline** — 1 — 1,576 tests cite no budget/ledger coverage; mutation sweeps ignore cost modules.
5. **Risk** — 5 — Autonomous loops across three paid engines without real-time spend visibility is a runaway-budget ship-blocker.

6. **Top blocker** — A single human-readable `harness budget today` command (or `--costs` flag on `today`) printing per-engine and total session spend, backed by at least one pytest on ledger arithmetic.
7. **Verdict** — HOLD — the harness can spend money autonomously but cannot yet show the operator what was spent; ship when cost visibility matches dispatch velocity.
