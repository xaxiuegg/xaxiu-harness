<!-- name=K16-SPEC-CULTURE latency_ms=71940 error='' -->

## Score

1. **Correctness — 2**: W8-STOP-HOOK’s spec claimed exclusions absent until follow-through commit `7081d93`, and the `EngineHealth.status` Literal omitted `quarantined`/`recovering` that production code was already writing.
2. **Robustness — 3**: Failure modes (schema rejection, hook noise) are patched in follow-throughs rather than anticipated in the original spec.
3. **Operator-usability — 3**: Runbook and `harness today` exist, but DPAPI seeding is invisible (W10 todo) and W8-OPERATOR-RUNBOOK criteria are soft enough to flip PASS/STOP.
4. **Test discipline — 4**: 1,576 tests catch code regressions, yet persistent STOPs on spec-audit rows prove acceptance criteria aren’t crisp enough to be spec-driven or automatable.
5. **Risk — 4**: W9’s 14-row backlog will amplify spec debt if implementation continues to outpace `spec/*.md`.

**Top blocker**: Gate every W9 row on a frozen `spec/*.md` that passes `harness spec-verify` before code is written; retroactively patch W8-STOP-HOOK and W8-PREFLIGHT-FIX specs to match commit `7081d93`.

**Verdict**: SHIP-WITH-FIXES — Spec culture is retroactive-edit, not lead; freeze specs pre-implementation or spec debt will outpace test coverage.
