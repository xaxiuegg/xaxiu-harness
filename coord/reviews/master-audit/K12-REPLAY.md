<!-- name=K12-REPLAY latency_ms=47768 error='' -->

## Score

1. **Correctness — 2**  
   `replay` claims v1/v2 coord-run reconstruction in help, yet no spec or shipped Wn row validates decision-chain fidelity.

2. **Robustness — 2**  
   Peer CLI verbs (`today`, `preflight`) time out after 30 s; replay lacks visible truncation or streaming guards for long histories.

3. **Operator-usability — 1**  
   The non-technical runbook never mentions `replay`, and truncated CLI help offers no cue on when or why to invoke it.

4. **Test discipline — 1**  
   The 1,576-test roll-up and mutation tables omit replay entirely; a regression in reconstruction logic would go unnoticed.

5. **Risk — 3**  
   Without usable replay, the operator cannot self-service investigate coord-run failures, guaranteeing future L5 escalations.

6. **Top blocker**  
   Add a runbook section “Investigate a failed coord run” that demonstrates `harness replay --human` with plain-language decision narration and sample output.

7. **Verdict — SHIP-WITH-FIXES**  
   Replay is technically present but operator-invisible; the runbook gap turns decision archaeology into dead code.
