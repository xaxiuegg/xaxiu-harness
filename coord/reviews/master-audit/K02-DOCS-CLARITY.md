<!-- name=K02-DOCS-CLARITY latency_ms=59650 error='' -->

## Score

1. **Correctness — 3**  
   CLI help and `harness today` are accurate, but the runbook omits DPAPI seeding paths and stop-hook behavior still confuses auditors, so docs do not fully match system reality.

2. **Robustness — 3**  
   Recovery flows (`preflight --fix`, `engines-heal`) are documented, yet the runbook lacks guidance on DPAPI/key-loss failure modes and hook noise, leaving operators unprepared for common faults.

3. **Operator-usability — 3**  
   Plain-language CLI output is strong, but a non-technical operator still cannot onboard cold: the runbook hides where secrets come from and `--profile non_technical` is not the default.

4. **Test discipline — 1**  
   No automated regression tests for README, runbook, or spec clarity; the only guard is the non-deterministic MiMo audit, which is process, not test coverage.

5. **Risk — 4**  
   A docs gap that blocks a non-technical operator from rotating keys or understanding hook noise is a near-term ship-blocker for unsupervised operation.

6. **Top blocker**  
   Add the DPAPI seeding section and `--profile non_technical` default instructions to `docs/OPERATOR_RUNBOOK.md` (the W10 todo already flagged) so setup and recovery are fully visible.

7. **Verdict — SHIP-WITH-FIXES**  
   Operator-facing surfaces are 80 % there, but the remaining 20 % are exactly the gaps that strand a non-technical user on first contact.
