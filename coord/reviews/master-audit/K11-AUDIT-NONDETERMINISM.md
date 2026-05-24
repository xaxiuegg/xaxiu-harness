<!-- name=K11-AUDIT-NONDETERMINISM latency_ms=63000 error='' -->

## Score

1. **Correctness — 3** Code appears correct, but the verification loop is a random variable; you cannot ship confidence when the auditor flips on identical bits.
2. **Robustness — 2** Silent quarantine failures and an accepted “ignore persistent STOPs” precedent mean the safety net catches nothing by design.
3. **Operator-usability — 3** Track B CLI is excellent, yet asking a non-technical operator to parse MiMo mood swings turns quality assurance into astrology.
4. **Test discipline — 3** 1576 tests and cleared mutation gates are solid, but the deferred canary is the only deterministic guardrail and it is not running.
5. **Risk — 4** A real regression will ride the W6-PANEL precedent through the gate because STOPs are now treated as noise until proven otherwise.

**Top blocker:** Deploy a 3-sweep majority-rule auditor (`W9-AUDIT-NONDETERMINISM-AVG`) with multi-commit diff anchors (`W9-AUDIT-ANCHOR-MULTI-COMMIT`); stop treating a single MiMo run as a binary gate.

**Verdict:** SHIP-WITH-FIXES — the harness is functional but its quality gate has worse SNR than a coin flip; calibrate it before W9 planning begins.
