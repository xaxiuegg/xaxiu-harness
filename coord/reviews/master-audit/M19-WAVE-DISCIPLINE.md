<!-- name=M19-WAVE-DISCIPLINE latency_ms=25821 error='' -->

## Score — Wave Discipline Lens

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3/5 | Loop is formally followed (plan→execute→audit→closeout) but audit verdicts are non-deterministic — 3 rows flip PASS↔STOP on identical code, making the gate decorative rather than load-bearing. |
| **Robustness** | 2/5 | The `except Exception: continue` in quarantine writes shipped undetected until audit sweep 2; audit non-determinism means real bugs and noise are indistinguishable at gate time. |
| **Operator-usability** | 4/5 | Runbook, `harness today`, `preflight --fix`, `engines-heal` — all genuine operator-readiness lifts. Persistent STOPs on these rows are auditor noise, not UX gaps. |
| **Test discipline** | 3/5 | 1576 tests, +32 net. But zero tests caught the silent EngineHealth schema failure; the audit (not the test suite) found the load-bearing bug. |
| **Risk** | 3/5 | Non-deterministic audit gates risk two failure modes: (a) real bugs get PASS-by-luck and ship; (b) clean code gets STOP-by-luck and blocks. Both compound across waves. |

## Top Blocker

**Ship W9-AUDIT-NONDETERMINISM-AVG (`--avg-of-N`) and re-run the 3 non-det rows as the validation case.** Until the audit gate produces stable verdicts on unchanged code, the plan→execute→audit→closeout loop has a broken leg — operators can't trust the audit as a shipping decision.

## Verdict

**SHIP-WITH-FIXES.** The wave-discipline loop is structurally sound — all 8 rows shipped, closeout doc is thorough, follow-through commits address real bugs — but the audit gate's non-determinism degrades it from a reliable quality gate to a coin flip, which will erode operator trust if left unresolved into W9+.
