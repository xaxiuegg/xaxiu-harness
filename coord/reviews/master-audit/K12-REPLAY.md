<!-- name=K12-REPLAY latency_ms=60380 error='' -->

## Score
1. **Correctness** — 3: The command exists for v1/v2 reconstructions, but zero operator-facing artifacts (runbook, `today`, preflight) describe when to invoke it, so the decision-archaeology promise is unfulfilled.
2. **Robustness** — 3: The tool likely tolerates truncated logs, yet the operator's mental model is fragile—without guided entry points they will not use it under pressure.
3. **Operator-usability** — 2: Completely absent from `harness today` suggested actions and the runbook excerpts shown; indistinguishable from a debug utility for engineers, not a non-technical operator.
4. **Test discipline** — 2: No test row or canary sweep validates the operator replay journey; a regression in CLI flags or output schema would only be caught by chance.
5. **Risk** — 3: The next time an engine quarantines or a dispatch loops, the operator lacks self-service archaeology, forcing escalation to engineering for decisions that replay data already holds.

6. **Top blocker** — Add a `--human` flag to `replay` that emits a numbered decision narrative (why engine X, why stop, what diff) and link it from `harness today` whenever audit STOPs or dead engines appear.

7. **Verdict** — SHIP-WITH-FIXES: The harness is operator-ready for day-to-day driving, but `replay` is a dead verb until decision-archaeology is surfaced in the daily pulse and runbook for non-technical users.
