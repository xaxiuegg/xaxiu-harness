<!-- name=K09-COSTS-BUDGET latency_ms=44348 error='' -->

## Score

1. **Correctness** — 2/5. `harness budget` exists but no verified output proves session-cost accuracy; `harness today` (daily pulse) times out, so the W6-A2 ledger wiring is not demonstrably readable.  
2. **Robustness** — 2/5. `preflight --skip-engines` and `today` both timeout after 30 s; the budget query path likely shares the same blocking init overhead.  
3. **Operator-usability** — 2/5. A non-technical operator cannot answer “how much did this session cost” when the plain-language pulse command fails and the runbook omits budget-reading steps.  
4. **Test discipline** — 1/5. None of the 1,576 cited tests target budget-meter accuracy or cost-ledger regression; W7-WORKER-BUDGET-HOOK landed without noted coverage.  
5. **Risk** — 4/5. Unverified spend visibility means the operator could accumulate API costs without a trusted single-command check.

6. **Top blocker** — Make `harness budget` (or `today`) return a sub-5-second, non-blocking per-session cost table and add one budget-meter assertion to the mutation-canary suite.  
7. **Verdict** — SHIP-WITH-FIXES. The ledger may be wired, but the operator-facing read-path is neither proven nor robust.
