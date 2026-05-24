<!-- name=K01-ONBOARDING latency_ms=135941 error='' -->

## Score
1. **Correctness** — 3/5. Preflight returns 0 fails but surfaces three unrelated warnings; a “successful” run still leaves the fresh clone in an unusable state (unregistered loops, dead engines, observer timeout).
2. **Robustness** — 3/5. `--fix` and `engines-heal` exist, yet the onboarding path scatters recovery across disparate commands rather than one resilient funnel.
3. **Operator-usability** — 2/5. A non-technical operator must independently decide to ignore warnings, run `--fix`, run `loop start`, or debug an observer timeout before the first healthy tick; DPAPI seeding is invisible and `--profile non_technical` is not the default.
4. **Test discipline** — 2/5. 1,576 unit tests pass, but the golden-path “clone → first green preflight” integration for a non-technical operator is unguarded.
5. **Risk** — 4/5. High probability the operator misses loop registration or DPAPI setup, misinterprets warnings as errors, and abandons or misconfigures the harness.

6. **Top blocker** — Wire `harness install` (already labeled a “first-run wizard”) into `preflight` so a fresh clone detects an uninitialized state and routes the operator through one idempotent command that sets the non-technical profile, registers the loop task, seeds DPAPI, and quarantines dead engines.
7. **Verdict** — SHIP-WITH-FIXES. The recovery primitives exist, but the hand-off from clone to first trustworthy preflight still demands debugging rather than reading.
