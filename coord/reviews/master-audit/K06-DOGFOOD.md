<!-- name=K06-DOGFOOD latency_ms=62500 error='' -->

## Score

**Correctness — 3**  
Ships features reliably, but the audit gate persistently STOPs its own hook and prompt tuning, indicating the spec-to-verification loop is self-inconsistent.

**Robustness — 3**  
Healing, fallback, and quarantine exist, yet `except Exception: continue` swallowed schema violations and the observer probe times out—silent failures in the self-monitoring layer.

**Operator-usability — 4**  
`today`, `status human`, and the runbook are genuinely accessible, but audit non-determinism forces a non-technical operator to ignore red flags, eroding trust.

**Test discipline — 3**  
1576 tests and a mutation canary show volume, yet the `EngineHealth` schema regression and audit-flip noise both escaped automated detection in the meta-layer.

**Risk — 3**  
The harness is becoming a tower of indirection where process (STATUS.csv at 310 rows, audit panels, canary manifests) could outpace product; audit drift threatens autopilot legitimacy.

**Top blocker**  
Ship `W9-AUDIT-NONDETERMINISM-AVG` with `--avg-of-N ≥ 3` and hard-fail only on consensus, eliminating MiMo noise so the audit gate can judge itself.

**Verdict**  
SHIP-WITH-FIXES: the dogfood loop is productive but the meta-layer currently cannot reliably audit its own audits, creating a recursive credibility gap.
