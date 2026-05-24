<!-- name=M07-MUTATION-COVERAGE latency_ms=28836 error='' -->

## Score

**Correctness (3):** The ≥3 gate is met for all 5 hot modules — the spec says what it says and the code delivers. But the spec itself is narrow: 5 modules out of ~40 production files get mutation coverage. The gate is correct *for its scope*; the scope is insufficient.

**Robustness (2):** W8 did not re-run the sweep. W9-MUTATION-MANIFEST has 3 warm-tier modules with `last_sweep_sha=null`. Three of the five tracked modules had 0.00 kill rate as recently as W6 and only recovered because they were explicitly targeted. No mechanism auto-fires a mutation run when a hot-module file changes — regressions land silently until the next manual sweep.

**Operator-usability (2):** A non-technical operator has no CLI verb to see which modules are mutation-tracked, what the kill rates are, or whether a sweep is stale. `harness today` and `harness status human` surface test counts and audit verdicts but not mutation coverage. The operator cannot distinguish "covered and green" from "never tested."

**Test discipline (3):** Tests exist that *generate* mutation scores, and 1576 tests pass. But 0 tests assert that the mutation manifest is consistent (e.g., "every `src/harness/**/*.py` appears in at least one tier"). The gate itself — "≥3 kill rate" — has no property-test verifying it's applied on every CI run or preflight cycle.

**Risk (3):** The sustainable bar is the real question. ≥3 is fine for a codebase with 5 tracked modules. At 10 modules, you need 10 sweeps. At 20, the sweep cost dominates. No tier graduation policy exists — modules never move from warm to hot. W10-FRESH-CANARY-MODULES is queued but unshipped, meaning 3 manifest gaps persist.

**Top blocker:** Execute `W10-FRESH-CANARY-MODULES` immediately (3 canary runs, ~30 min total) to populate `last_sweep_sha` for the 3 warm-tier nulls. Then add a preflight check: `mutation_manifest_completeness` that fails if any tier has `null` sha older than 7 days. This makes the ≥3 gate *self-enforcing* rather than manually refreshed.

**Verdict:** SHIP-WITH-FIXS. The gate works for the 5 modules it covers; the coverage gap and stale-sweep risk are real but addressable in one focused session.
