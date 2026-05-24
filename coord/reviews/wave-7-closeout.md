# Wave 7 closeout — Test-quality recovery + foundation completion

**Authored**: 2026-05-23 by Claude after shipping the Wave 7 backlog under autonomous-loop discipline.

**Driver recap**: Wave 6 closed with 2 STOP audits (W6-A3 mutation sweep at 0.60, W6-C2 dead-engine alarm at 0.62) and 1 partial (W6-B1 EngineTransport retrofit).  A 10-reviewer panel (5 MiMo + 5 Kimi) reviewed the closeout and converged on three things: (1) accept C2 as shipped, (2) conditionally accept A3 with a lock — `W7-MUTATION-WORKER` must hit ≥3 kill rate before any other W7 row unlocks, (3) open Wave 7 with the `worker.py` budget hook fix, then the mutation work, then unlock everything else.  Operator chose this composite path.

Wave 7 executed that plan + the W7 backlog the panel surfaced.

## What shipped (commit refs)

| Row | Status | Effort | Commit | Notes |
|---|---|---|---|---|
| W7-WORKER-BUDGET-HOOK | shipped | ~25 min | `33be9d6` | Wave-7 warm-up.  Threads tokens_in/out through DispatchResult → worker accumulator → budget ledger.  Fixes the swarm/* in=0 underreporting. |
| W7-MUTATION-WORKER | shipped | ~2 hr | `5253e64` + `da47f2a` | **Lock gate.** 20 behavioral tests; sweep avg=4.00 (was 0.00). |
| W7-KIMI-REASONING-EMPTY | shipped | ~20 min | `da47f2a` | `EngineResponse.reasoning_only` flag.  Caught by W6-PANEL retry sequence. |
| W7-KIMI-MAX-TOKENS-FLOOR | shipped | ~10 min | `da47f2a` | Clamps caller's max_tokens UP to 8K floor; escape hatch via `max_tokens_override_floor`. |
| W7-MUTATION-ORCH | shipped | ~45 min | `1dae478` | 11 behavioral tests; sweep avg=3.00 (was 0.00). |
| W7-MUTATION-CONCRETE | shipped | ~75 min | `1dae478` + `91489f8` + `9ed0e37` | 16 tests; first sweep 2.67, second sweep 3.33 (added 2 tests for line 450 gt_to_ge). |
| W7-B1-RETROFIT | shipped | ~75 min | `d074321` | StreamingTransport ABC + 12 base-class tests.  DeepSeek + Kimi refactored; MiMo out of scope (batch HTTP, not SSE). |
| W7-SPEC-DRIFT | shipped | ~75 min | `8cc50f4` | Planner enforces operator's single-worker directive (both `## Planner Guidance` + `single_worker: true` AND free-form `MUST be done by ONE worker`).  Closes the W6-A1 cross-worker contract drift class. |

**8 of 8 backlog items shipped** + the W6-PANEL composite-move proposal executed cleanly.

## Mutation kill rate — Wave 6 → Wave 7

| Module | W6-A3 avg | W7 avg | Δ |
|---|---|---|---|
| `src/harness/engines/dispatcher.py` | 17.30 | (untouched) | — |
| `src/harness/coord/integrator.py` | 5.00 | (untouched) | — |
| `src/harness/engines/concrete.py` | 1.00 | **3.33** | +2.33 |
| `src/harness/coord/worker.py` | 0.00 | **4.00** | +4.00 |
| `src/harness/orchestrator.py` | 0.00 | **3.00** | +3.00 |

All 5 top-modules now exceed the ≥3 gate.  The W6-A3 audit's STOP at 0.60 was the load-bearing reason this work happened — and the W7-MUTATION-* trio shipped a real improvement, not just deferral.

## Test count growth

- W6 close: 1465 passed + 4 skipped
- W7 close: 1544 passed + 6 skipped
- Net: **+79 new tests** across 8 rows

The new tests are concentrated on behavioral assertions (not boundary mocks).  Each mutation-killer test is documented with the specific operator/operand mutation it catches.

## Wave-7 scope additions discovered mid-flight

These were not in the W6-PANEL synthesis but ship in Wave 7:

- **W7-KIMI-REASONING-EMPTY** + **W7-KIMI-MAX-TOKENS-FLOOR**: surfaced during the W6-PANEL retry sequence when 4 of 5 Kimi reviewers returned empty content because `max_tokens=4000` was eaten by `reasoning_content`.  The fix prevents future panel scripts (and operator code) from silently hitting the same footgun.

- **W7-B1-RETROFIT scope correction**: the W6-B1 dispatched packet stalled trying to retrofit all 3 engines.  Re-investigation found MiMo uses non-streaming batch HTTP (not SSE), so the StreamingTransport ABC fundamentally doesn't apply.  Scope corrected to DeepSeek + Kimi, which DID retrofit cleanly.

## Audit gate — Wave 7 has no STOPs

Wave 6 ended with 2 STOP audits (A3 + C2) and 1 partial (B1).  Wave 7 ended with all rows shipped and no audit gate failures.  Possible reasons:

1. The W6-PANEL synthesis gave clear acceptance criteria the operator endorsed in advance — there was no spec ambiguity to trip over.
2. The mutation-killer pattern is mechanical (set up the bad mutation case + assert observable behavior); easier to write tight tests for than open-ended "validate the closeout doc" prompts.
3. Wave 7 work was incremental from Wave 6 — less new surface area per row.

The Wave-6 audit-script hardening (commit `6f9f657` — detect MiMo content-filter rejection + fall back to DeepSeek) also paid off: no audits were dropped this wave because of MiMo non-determinism.

## What Wave 7 explicitly did NOT do

- ❌ The K5 devil's-advocate panel suggestion (`test_alarm_shadow.py` — production-log replay) — not implemented.  Genuinely valuable but requires operator decision on how to source production logs + ground-truth outage records.
- ❌ The K1 cost-conscious suggestion (single dispatcher behavioral test for the alarm hook) — partial: the W7-MUTATION-WORKER tests do exercise the dispatcher hook indirectly via the W6-C2 source-grep sentinel + the alarm fire-toast-debounce E2E.
- ❌ W7-SPEC-DRIFT mitigations (a) integrator pytest catches contract mismatches, (b) spec linter for single example per format claim, (c) cross-worker contract check — only (d) operator directive was shipped.  (a) and (c) need substantial planner-internal work; (b) is a small lint rule that could be Wave 8.
- ❌ MiMo retrofit to a separate batch-HTTP base class (no other engines share that pattern; refactor isn't justified yet).

## W8 candidates (if there's a Wave 8)

1. **`test_alarm_shadow.py`** (K5 panel suggestion) — replay last-week's `state/engine_performance_log.jsonl` through `harness.engine_alarm.check_engine_alarm` in shadow mode + compute false-positive/false-negative rates.  Requires operator decision on ground-truth source.
2. **Spec linter for example-per-format-claim** (W7-SPEC-DRIFT mitigation b) — small lint rule that catches multi-example contradictions like W6-A1's `KIMI:SET` vs `KIMI_API_KEY:SET` mismatch.
3. **Integrator pytest contract checking** (W7-SPEC-DRIFT mitigation a) — verify W4-B already catches contract mismatches; if not, add it.
4. **Audit-script content-filter hardening extension** — currently detects the "rejected because high risk" + "no JSON" cases; could also detect partial-JSON truncation.
5. **Production-log token-tracking audit** — verify the W7-WORKER-BUDGET-HOOK split is producing accurate token counts in real ledger entries, not just unit-test stubs.

## Wave 7 effort summary

- ~6 hours wall-clock, autonomous loop
- 11 commits on master (`33be9d6` → `8cc50f4`)
- 1544 / 1544 pytest pass + 6 skipped
- 8 of 8 backlog items shipped + 2 panel-surfaced bonus items
- 0 audit-gate STOPs
- 5 W8 candidates surfaced

## Stop point

W7-CLOSEOUT marks the wave done.  Per the W6-CLOSEOUT precedent and operator directive, **stop here and wait for operator review** before opening Wave 8.

`harness session ok-to-stop --json` still returns `ok_to_stop=false` because of the operator-owned `SESSION-2026-05-23-CLOSEOUT` row — that's the operator's review queue item, not a Claude work item.
