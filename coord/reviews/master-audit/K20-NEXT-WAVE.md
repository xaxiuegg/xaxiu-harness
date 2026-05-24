<!-- name=K20-NEXT-WAVE latency_ms=44273 error='' -->

## Score
1. **Correctness** — 3: Persistent STOPs on STOP-HOOK and AUDIT-PROMPT show the detection layer itself is still unreliable.
2. **Robustness** — 3: Silent schema quarantine bug persisted for waves; observer timeouts show failure modes still escape.
3. **Operator-usability** — 4: Runbook, `today`, and `engines heal` unblocked the non-technical operator.
4. **Test discipline** — 3: 1576 tests exist, but audit gate flips PASS/STOP on identical commits, eroding signal trust.
5. **Risk** — 4: Undependable detection is a near-term ship-blocker; regressions can slip in silently.

## Plus
6. **Top blocker** — Wave 9 must prioritize **detection** first. Stack-rank: detection > operator UX > engine reliability > v2 maturity > scope reduction. The audit gate needs deterministic DeepSeek-primary averaging (`W9-AUDIT-NONDETERMINISM-AVG` is queued but unshipped), and the stop-hook must reach persistent PASS. Without hardened detection, every later wave builds on sand.
7. **Verdict** — SHIP-WITH-FIXES: operator day-to-day is viable, but detection must be hardened before any scope expansion.
