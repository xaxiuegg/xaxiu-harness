<!-- name=K20-NEXT-WAVE latency_ms=64593 error='' -->

## Score

1. **Correctness — 3**  
Persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT mean the detection layer does not yet meet its own spec; the schema-bug fix proves silent failures were slipping through.

2. **Robustness — 3**  
`except Exception: continue` masked a load-bearing schema mismatch for an unknown duration; observer probes time out; detection noise undermines failure response.

3. **Operator-usability — 4**  
Preflight --fix, `today`, engines-heal and the runbook clear W8 readiness blockers, though `--profile non_technical` still is not the default.

4. **Test discipline — 3**  
1576 tests pass and mutation rates exceed gates, yet the quarantine path had zero coverage for the invalid-Literal rejection that silently broke every health write.

5. **Risk — 4**  
W9 must stack-rank detection > operator UX > engine reliability > v2 maturity > scope reduction; without a deterministic audit gate, regressions slip in silently or reviewer trust collapses under false-positive fatigue.

## Top blocker

Ship `W9-AUDIT-NONDETERMINISM-AVG` and eliminate the two persistent STOP rows so the audit gate becomes a trustworthy signal rather than a source of noise.

## Verdict

SHIP-WITH-FIXES — operator readiness is good enough to proceed, but W9 must not layer new features atop an audit gate that cries wolf (or stays silent on real wolves).
