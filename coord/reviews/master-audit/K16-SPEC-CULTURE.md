<!-- name=K16-SPEC-CULTURE latency_ms=49690 error='' -->

## Score

1. **Correctness — 3**  
   The Wave 8 closeout spec matches the code because it was authored *after* shipping (dated 2026-05-24, yet commits `9aea866` and `3dc8593` landed earlier). It is a chronicle, not a blueprint.

2. **Robustness — 2**  
   Retroactive specs offer no design-time guardrails. The `EngineHealth` schema bug silently failed every quarantine, and `preflight --fix` auto-stashed work—both surprises a spec-first review could have prevented.

3. **Operator-usability — 3**  
   The runbook and `harness today` are usable, but the non-technical operator cannot read an up-front spec to anticipate behavior or withhold authority before code ships.

4. **Test discipline — 2**  
   1,576 tests pass, yet there is no deterministic spec-to-code gate. MiMo audits are non-deterministic, the mutation-canary is deferred to W9, and the persistent STOPs on `W8-STOP-HOOK` and `W8-AUDIT-PROMPT` show spec compliance is verified erratically.

5. **Risk — 4**  
   Wave 9 is already queueing work (`W9-PREFLIGHT-FIX-NOSTASH`, `W9-MUTATION-CANARY`). Without a spec-first mandate, the next wave will repeat emergent development and operator surprise.

**Top blocker:**  
Freeze a `spec/wave-9-plan.md` and require operator sign-off *before* the first W9 implementation commit. Specs must lead; closeouts must not substitute for design review.

**Verdict:** SHIP-WITH-FIXES. W8 delivers operator-ready functionality, but the spec culture is backward-looking. If Wave 9 is not spec-led, operational trust and auditability will degrade.
