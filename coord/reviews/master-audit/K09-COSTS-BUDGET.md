<!-- name=K09-COSTS-BUDGET latency_ms=47032 error='' -->

## Score

1. **Correctness — 2**  
   `budget` CLI exists but snapshot shows no per-session cost attribution; ledger wiring is opaque.

2. **Robustness — 2**  
   No cost-cap alarms, overrun circuit breakers, or pricing-drift guards visible in preflight or `today`.

3. **Operator-usability — 1**  
   `harness today` omits spend entirely; a non-technical operator has no obvious one-command answer for session cost.

4. **Test discipline — 1**  
   1,576 tests cite zero ledger-reconciliation or cost-accuracy coverage; mutation table ignores budget modules.

5. **Risk — 3**  
   Silent spend accumulation across Kimi/DeepSeek/MiMo with no meter visibility is a credible 30-day bill shock.

6. **Top blocker**  
   Add a plain-language cost stanza to `harness today` (or a `harness budget --last-session` human output) so the operator can read spend without interpreting a ledger.

7. **Verdict**  
   SHIP-WITH-FIXES: plumbing is present but the operator lacks a single, human-readable command to answer "how much did this session cost."
