<!-- name=K11-AUDIT-NONDETERMINISM latency_ms=150166 error='' -->

## Score
1. **Correctness** — 3. The harness executes correctly, but the audit gate contradicts itself on identical commits, so its verdicts are not reliably correct.
2. **Robustness** — 2. A gate that yields PASS and STOP for the same SHA under replication is brittle; robustness requires stable output under identical input.
3. **Operator-usability** — 3. The operator can drive the CLI, but audit roulette creates toil—forcing reruns or training them to ignore STOPs.
4. **Test discipline** — 3. Strong unit coverage (1576 tests), yet no golden-set test enforces verdict stability across repeated audits of a fixed commit.
5. **Risk** — 4. Next 30 days: real gaps may be dismissed as MiMo noise, while false STOPs burn review cycles on harmless rows.

6. **Top blocker** — Codify the shipped DeepSeek-primary + --avg-of-N infrastructure into a binding panel protocol: require ≥3 runs, discard outliers, enforce σ<0.10 and mean confidence ≥0.75 before a PASS/STOP is recorded.
7. **Verdict** — SHIP-WITH-FIXES. The harness is operator-ready, but a quality gate noisier than its signal is a liability; calibrate it to a stable, consensus-based standard before relying on it for ship decisions.
