<!-- name=M04-OBSERVABILITY latency_ms=33174 error='' -->

## Score

1. **Correctness** — 3/5. Surfaces reflect state but `harness today` truncates after 110 items; operator can't see the full picture without digging into STATUS.csv.
2. **Robustness** — 3/5. Observer probe timeout shows one retry warning; preflight shows fixable warnings. No proactive alerting when surfaces degrade.
3. **Operator-usability** — 2/5. `harness today` is friendly, but default profile is technical, STATUS.csv is raw 309-row CSV, and dashboard requires manual start/stop. Non-technical operator must switch contexts.
4. **Test discipline** — 3/5. Observer has tests; status tracker is tested. Mutation testing covers dispatch and integration but observability surfaces not prioritized in mutation sweeps.
5. **Risk** — 2/5. Scattered surfaces mean operator might miss a quiet failure until it escalates. Not a ship-blocker but friction.

## Top blocker
Set `--profile non_technical` as the default so `harness today`, preflight, and status automatically show the human-friendly format without requiring the operator to remember a flag.

## Verdict
SHIP-WITH-FIXES — Observability is functional but the operator has to toggle between friendly and technical views; a default profile flip and a persistent dashboard would cut the digging in half.
