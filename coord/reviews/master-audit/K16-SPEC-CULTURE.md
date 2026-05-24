<!-- name=K16-SPEC-CULTURE latency_ms=70977 error='' -->

## Score

1. **Correctness — 2**  
   The W8-PLAN spec at `9aea866` preceded its implementation rows, yet the `EngineHealth` schema (`Literal["up","degraded","down"]`) was stale against the quarantine logic, causing silent failures; persistent MiMo STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT signal residual drift.

2. **Robustness — 2**  
   `spec-verify` and `lint-spec` provide provenance tracking, but the commit hook (W8-STOP-HOOK) is a persistent audit failure and needed retroactive exclusion tuning, showing the spec gate frays under real repo churn.

3. **Operator-usability — 4**  
   Non-technical operators can scaffold, lint, and SHA-verify specs via `harness spec-init / lint-spec / spec-verify` without touching Python.

4. **Test discipline — 2**  
   Every Wn row gets a MiMo audit, but identical commits produce PASS/STOP flips (W8-ENGINES-HEAL, STATUS-HUMAN), so the gate detects noise more reliably than drift.

5. **Risk — 3**  
   If the audit gate is perceived as random, developers will silence or skip it, and specs will diverge from code just as the `EngineHealth` schema did.

6. **Top blocker**  
   A deterministic `spec-verify --fresh` pre-commit check that maps each `spec/*.md` acceptance-criteria bullet to an existing CLI verb, schema field, or test path, replacing MiMo as the sole drift detector.

7. **Verdict** — SHIP-WITH-FIXES. Spec-first process exists but lacks a trustworthy mechanical freshness check; once deterministic, the culture will stick.
