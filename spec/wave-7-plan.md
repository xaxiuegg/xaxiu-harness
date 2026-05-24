# SPEC-ID: wave-7-plan — Test-quality recovery + foundation completion

**Authored**: 2026-05-23 retrospectively, after the wave shipped, so the
MiMo audit gate can score each row against explicit acceptance criteria
(matching the W6-PLAN pattern).

**Driver**: Wave 6 closed with 2 STOP audits (A3 mutation sweep at 0.60,
C2 dead-engine alarm at 0.62) and 1 partial (B1 EngineTransport
retrofit).  A 10-reviewer panel (5 MiMo + 5 Kimi) reviewed the closeout
and converged on a composite move: accept C2 as shipped, conditionally
accept A3 with `W7-MUTATION-WORKER` as a backlog-lock gate, open Wave 7
with the worker.py budget hook warm-up, then ship the mutation work,
then unlock the rest.  Operator chose this path.

## Policy: every Wn action gets a MiMo audit (operator directive
2026-05-23)

Per operator: extend the W6-PLAN per-task audit gate to ALL Wn work
going forward.  Every shipped W6/W7/W8/... row must have an audit
report at `coord/reviews/audits/<stamp>_<task-id>_audit.md`.
Wave-7 shipped before this directive landed; this plan exists to give
the retroactive audits explicit acceptance criteria to score against.

## Tasks (acceptance criteria mirror what was shipped)

#### W7-WORKER-BUDGET-HOOK — fix worker.py input_tokens=0 hardcode

**Steps**:
1. Add `tokens_in` and `tokens_out` fields to `DispatchResult`.
2. Populate them in `dispatch_packet` when building the success-path
   result.
3. Forward through `_dispatch_via_swarm`'s `SimpleNamespace`.
4. Split worker.py's `total_tokens` accumulator into `total_tokens_in`
   and `total_tokens_out`.
5. Update worker.py's `_budget_record` call to use the split.
6. Preserve legacy "everything to output_tokens" for swarm CLI paths
   (where the engine doesn't surface a split).

**Acceptance**:
- DispatchResult exposes `tokens_in` / `tokens_out` (default 0; sum
  still available as `tokens_used`)
- `harness budget summary` reflects in/out separately for direct-HTTP
  engines (no regression of swarm CLI totals)
- ≥3 tests covering: split-recording happy path, legacy-aggregate
  fallback, DispatchResult schema sentinel

#### W7-MUTATION-WORKER — push worker.py mutation kill rate from 0.0 to ≥3

**Steps**:
1. Add behavioral tests in `tests/test_worker_mutation_killers.py`
   targeting the FIRST occurrence of each mutation pattern the
   W6-A3 sweep applied.
2. Run `scripts/run_mutation_sweep.py` against worker.py only and
   confirm avg ≥3.

**Acceptance**:
- Mutation sweep on `src/harness/coord/worker.py` yields avg ≥3
- Tests assert OBSERVABLE behavior (mutation kill, not mock rubber-
  stamp); semantically-benign mutations (e.g. `> 0` vs `>= 0` where
  both branches converge) documented as not-kill-target
- Full pytest stays green

#### W7-KIMI-REASONING-EMPTY — surface reasoning_only on Kimi empty content

**Steps**:
1. Add `reasoning_only: bool = False` field to `EngineResponse`.
2. In `KimiConcrete.dispatch`, set reasoning_only=True when content
   chunks=[] and reasoning chunks>0.

**Acceptance**:
- EngineResponse has `reasoning_only` field with default False
- Kimi sets it correctly on the reasoning-exhausted-budget case
- Test coverage: reasoning_only=True for content=[]/reasoning>0;
  reasoning_only=False for content present; reasoning_only=False
  default for parse_error paths

#### W7-KIMI-MAX-TOKENS-FLOOR — clamp small caller max_tokens to 8K safety floor

**Steps**:
1. In `KimiConcrete._build_payload`, clamp caller `max_tokens` UP to
   8000 if below that floor.
2. Provide an escape hatch via `extra_args["max_tokens_override_floor"]
   = True` for callers who genuinely need a tight cap.
3. Preserve the caller-omitted default at 200K (W5-W).

**Acceptance**:
- Caller `max_tokens=4000` becomes `max_tokens=8000` in payload
- Caller `max_tokens=2500` becomes `max_tokens=8000`
- Caller `max_tokens=8000` passes through unchanged
- Caller `max_tokens=1000` + `max_tokens_override_floor=True` →
  `max_tokens=1000` (escape hatch respected)
- Caller-omitted max_tokens still defaults to 200K

#### W7-MUTATION-ORCH — push orchestrator.py mutation kill rate from 0.0 to ≥3

**Steps**:
1. Add behavioral tests in `tests/test_orchestrator_mutation_killers.py`
   covering the merge-gating logic at line 170 (`st == "completed"`)
   + the integrate-success check at line 187 (`rc_int == 0`).
2. Run mutation sweep on orchestrator.py only and confirm avg ≥3.

**Acceptance**:
- Mutation sweep on `src/harness/orchestrator.py` yields avg ≥3
- All-workers-completed → merge fires; failed/in-progress worker
  blocks merge
- Integrate rc=0 → merged=True; rc>0 → merged=False with stderr in
  diagnostic

#### W7-MUTATION-CONCRETE — push concrete.py mutation kill rate from 1.0 to ≥3

**Steps**:
1. Add behavioral tests in `tests/test_concrete_mutation_killers.py`
   targeting the Anthropic block-type filter (line 138), DeepSeek
   parsed_anything (line 257), DeepSeek SSE [DONE] (line 235), and
   the Kimi reasoning_only check (line 450).

**Acceptance**:
- Mutation sweep on `src/harness/engines/concrete.py` yields avg ≥3
- Tests catch the specific operator/operand mutations the sweep
  applies, not boundary mocks

#### W7-B1-RETROFIT — complete the EngineTransport refactor

**Steps**:
1. Create `src/harness/engines/transport.py` with a
   `StreamingTransport` ABC (template-method dispatch + 3 hooks:
   `_process_delta`, `_finalize_response`,
   `_handle_remote_protocol_error`).
2. Refactor `DeepSeekConcrete` and `KimiConcrete` to inherit from it.
3. `MiMoConcrete` is OUT OF SCOPE (batch HTTP, not SSE).
4. Add direct tests for the ABC in `tests/test_engines_transport.py`.

**Acceptance**:
- StreamingTransport ABC owns SSE parse loop + prefix variants +
  [DONE] terminator + chunk JSON-decode + error mapping
- DeepSeek + Kimi subclasses' dispatch methods removed (replaced by
  3-method protocol: URL, headers, payload)
- Kimi's reasoning_only flag + RemoteProtocolError partial-content
  rescue preserved via hook overrides
- Existing tests still green; ≥10 new ABC tests

#### W7-SPEC-DRIFT — planner enforces operator's single-worker directive

**Steps**:
1. Add `_extract_single_worker_directive(spec_text)` helper to
   `planner.py` recognising both:
   - Free-form sentence: `MUST be done by ONE worker` (with
     `by a single worker` / `in ONE worker` synonyms)
   - Structured: `## Planner Guidance` section + `single_worker: true`
2. In `plan()`: when directive detected, prepend an OPERATOR
   DIRECTIVE banner to the planner prompt.
3. Post-hoc validate: if directive is True and `len(plan.tasks) != 1`,
   reject this attempt and retry with explicit feedback.  Raise
   ValueError if retries exhausted.

**Acceptance**:
- Both directive forms detected (case-insensitive)
- Synonyms ("by a single worker", "in ONE worker") detected
- Multi-task plan rejected with ValueError when directive present
- Single-task plan accepted; no false positives on specs without the
  directive
- Tests cover all 6 detection cases + 3 plan-level enforcement cases

#### W7-CLOSEOUT — Wave 7 closeout report

**Steps**:
1. Author `coord/reviews/wave-7-closeout.md` summarising all 8 W7
   rows, the W6-PANEL composite move executed, mutation kill rate
   improvements (0.0 → ≥3 for all 5 hot modules), test count growth,
   audit-STOP comparison (0 vs 2+1 partial), and W8 candidates.

**Acceptance**:
- Document exists at `coord/reviews/wave-7-closeout.md`
- All 8 W7 rows mentioned with commit refs
- Mutation kill rate table shows W6 → W7 deltas
- ≥3 W8 candidates surfaced for future review

## What's NOT in Wave 7

- ❌ MiMo retrofit (it's batch HTTP, not SSE — no shared pattern)
- ❌ K5 alarm shadow replay (requires operator decision on production
  log source + ground-truth outage records)
- ❌ K1 dispatcher behavioral test for alarm (covered indirectly by
  W7-MUTATION-WORKER + W6-C2 source-grep sentinel)
- ❌ W7-SPEC-DRIFT mitigations (a) integrator pytest contract check,
  (b) spec linter for example-per-format-claim, (c) cross-worker
  contract check — only (d) shipped this wave

## Audit gate behavior (per operator directive, all Wn)

Every shipped W6/W7/W8 row must be audited by running:

```powershell
PYTHONPATH=src python -X utf8 scripts/audit_task_with_mimo.py <task-id>
```

`<task-id>` matches the `#### <task-id>` header in this plan (or the
predecessor wave plans).  Audit confidence ≥ 0.7 to PROCEED; < 0.7 =
STOP for operator review.  Goodhart-trap avoidance is the same as
W6-PLAN: do NOT re-word audit prompts to be flattering; DO fix root
causes the auditor identifies.
