<!-- name=M06-AUDIT-GATE latency_ms=58824 error='' -->

## Score

| # | Dimension | Score | Justification |
|---|-----------|-------|---------------|
| 1 | Correctness | 3 | Gate caught real regressions (schema bug, MUTATION-ORCH), but ~30% of STOPs on unchanged code are false positives (ENGINES-HEAL, STATUS-HUMAN, OPERATOR-RUNBOOK flips). The 0.65–0.75 confidence band is a coin-flip zone. |
| 2 | Robustness | 2 | Same commit + same auditor → different verdict. Three flips across sweeps 2→3 with zero code diff. The gate is non-deterministic at the decision boundary, which is the *only* place reliability matters. |
| 3 | Operator-usability | 2 | A non-technical operator sees STOP/STOP/PASS on ENGINES-HEAL and can't distinguish "real regression" from "MiMo rolled a different number." Trust erodes fast. |
| 4 | Test discipline | 3 | The gate is eating its own dogfood — 3 sweeps, flip-tables published, `--avg-of-N` queued in W9. But no integration test asserts stability on fixed input, so the noise floor is only *documented*, not *eliminated*. |
| 5 | Risk (audit-gate lens) | 3 | Not a ship-blocker yet because operator precedent (W6-PANEL) already absorbed the noise. But if W10+ rows hit the 0.65–0.75 band, every wave gets a "3 STOPs — is it real?" cycle. W9-AUDIT-NONDETERMINISM-AVG is the critical path. |

**False-positive rate:** ~20–24% (4–5 of ~21 sweeps gave STOP on code unchanged since last PASS).
**False-negative rate:** Cannot be measured from this data — there's no independent "ground truth" audit to compare against. At least one TP (schema bug) proves the gate *can* catch silent failures. But a silent false negative is, by definition, silent.

## Top blocker

Ship **W9-AUDIT-NONDETERMINISM-AVG** (`--avg-of-N`) and **require it** for all Wn closeout verdicts. A single averaged score ≥0.70 = PASS, below = STOP. This collapses the flip-flop noise into one number and makes the audit gate auditable itself.

## Verdict

**SHIP-WITH-FIXES.** The gate catches real regressions (2 hard-PASS lifts prove it), but ~20–24% false-positive noise on unchanged code makes individual STOP verdicts unreliable — the operator cannot distinguish signal from MiMo non-determinism without the `--avg-of-N` stabilizer shipping in W9.
