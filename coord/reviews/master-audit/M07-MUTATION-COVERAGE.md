<!-- name=M07-MUTATION-COVERAGE latency_ms=35754 error='' -->

## Score

1. **Correctness**: 4 — Top-5 modules clear the ≥3 gate, but the full sweep wasn't re-run in W8, and the manifest notes modules with 0 kill-rate (observer/cycle) that need pattern expansion.
2. **Robustness**: 3 — The mutation canary and manifest exist, but MiMo audit non-determinism (which drives mutation checks) is a fragile layer; the `--avg-of-N` fix is queued but not shipped.
3. **Operator-usability**: 4 — The operator never directly touches mutation coverage, but the system's reliability underpins autonomous mode trust. The runbook and `harness today` abstract this well.
4. **Test discipline**: 4 — Mutation-orchestrator tests exist and the W8 schema-bug fix landed with tests. However, we lack proof that mutations kill bugs in the newly added W8 features (preflight-fix, engines-heal).
5. **Risk**: 3 — The main risk is coverage stagnation as the codebase grows. Without re-running the full sweep and expanding patterns for all warm-tier modules, the gate becomes a historical artifact, not a current guarantee.

## Top blocker

Run a full mutation sweep (not just canary) on the current HEAD and update `coord/mutation_targets.yaml` with fresh kill-rates for all modules. This would reveal which modules are currently untested and allow the ≥3 gate to be enforced globally, lifting my score by ≥1 on Correctness and Risk.

## Verdict

SHIP-WITH-FIXES. The ≥3 gate is currently met for the top 5, but the system's credibility as a regression net depends on continuous, comprehensive mutation sweeps—a practice not yet normalized.
