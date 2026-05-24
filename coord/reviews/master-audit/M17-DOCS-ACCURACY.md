<!-- name=M17-DOCS-ACCURACY latency_ms=33745 error='' -->

## Score

1. **Correctness** (3/5) — Docs claim "8/8 shipped" but the audit roll-up itself shows persistent STOPs on 2 rows; `harness today` shows 27 STOPs total — the closeout normalizes this as "non-determinism" rather than calling it what it is: the audit gate is unreliable.
2. **Robustness** (3/5) — Schema bug fix is real and load-bearing, but `preflight --skip-engines` snapshot still shows `dead_engines` as `[!]` — if the fix works, this output contradicts the claim. The doc's "manual verification" assertion can't be reproduced from the snapshot.
3. **Operator-usability** (4/5) — `harness today` is genuinely plain-language. Runbook exists. But 40+ CLI verbs in `--help` overwhelm a non-technical operator, and W10-PROFILE-AWARE-DEFAULTS confirms the profile default still isn't landed.
4. **Test discipline** (3/5) — +32 tests for 8 shipped items is thin. Mutation kill rate wasn't re-run in W8 despite the closeout calling it out. Persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT suggest the audit infrastructure itself lacks regression coverage.
5. **Risk** (3/5) — Governance risk: the doc frames audit non-determinism as "accepted per W6-PANEL precedent," effectively making the quality gate advisory-by-default. If the gate doesn't gate, what does?

## Top blocker

Resolve the persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT — either fix them or formally downgrade the audit gate from "required for done" to "advisory" in CLAUDE.md. Right now the doc simultaneously claims every row must pass audit *and* ships rows that never pass. That's a spec-vs-practice lie that will confuse every future session.

## Verdict

**SHIP-WITH-FIXES** — the operator-readiness Track B deliverables (preflight --fix, today, engines-heal, runbook) are genuinely useful and address real W8-panel blockers, but the closeout doc overstates certainty by packaging audit failures as "non-determinism" rather than unresolved gaps, and the audit gate itself needs a policy fix before it can be trusted as a quality control.
