# SPEC-ID: wave-6-plan — Validation, Foundation, Hygiene

**Authored**: 2026-05-23 by Claude after 5-MiMo session review

**Driver**: 5 MiMo reviewers gave the prior session 0.40 average confidence with one shared message — **stop shipping features, prove what's already built actually works, fix the foundation before adding more.** Wave 6 sequences their 5 directives into 3 phases with a MiMo audit gate after every task.

## Goal

Ship the operator's original turn-1 objective (one green end-to-end env-doctor run), validate test-suite integrity via mutation sweep, extract the EngineTransport abstraction Architect demanded, add the preflight gate Operator Advocate demanded, and fix the cross-project hook noise — with a MiMo audit between every task to catch silent-shipping bugs before they accumulate.

## MiMo audit gate (between every task)

After each task lands a commit, fire `scripts/audit_task_with_mimo.py <task-id>`. The audit:
- Reads the commit SHA + diff stat + commit message
- Reads the task's acceptance criteria from this plan
- Asks one MiMo Pro v2.5 agent: "Does this commit meet the acceptance criteria? What's missing? Confidence 0.0–1.0."
- Writes `coord/reviews/audits/<stamp>_<task-id>_audit.md`
- **Gate**: if confidence < 0.7, STOP. Surface to operator. Do not proceed to next task.
- **Pass**: confidence ≥ 0.7 → proceed.

This addresses the "ship-without-review" pattern the 5-MiMo session review identified.

## Strict Paths

- coord/reviews/wave-6-closeout.md

## Phases

### Phase A — Validate (prove the foundation isn't quietly broken)

#### A1 — Green env-doctor end-to-end run on all 3 engines (~45 min)

Operator turn-1 objective from the prior session that drifted. Closes the PM + Skeptical reviewer directives.

**Steps**:
1. Verify `spec/samples/env-doctor-check.md` is current (or refresh)
2. Drop into `spec/auto/`
3. Run `harness queue execute --once --planner-engine kimi-api --engine swarm/mimo --fallback-engine swarm/deepseek --no-merge`
4. Repeat with `--engine swarm/kimi-api`
5. Repeat with `--engine swarm/deepseek`

**Acceptance**:
- 3 separate `runs/<run-id>/checkpoints/worker-1.json` show `state=completed` + `tests_passed=true`
- STATUS.csv row `W6-A1-ENV-DOCTOR-E2E` marked shipped with all 3 run IDs
- Commit pushed

#### A1.1 — Investigate worktree-branching from `depends_on` parent [DISCOVERED + INVESTIGATED]

**Outcome**: D5 verified working. Initial diagnosis was wrong.

Empirical evidence from `runs/20260523T142354-79ed`:
- worker-2's branch log shows worker-1's commit `ec7fc51` in its history
- Re-running worker-2's tests in its still-existing worktree shows 22/22 pass
- The 3/22 test failures the worker reported at run-time are not reproducible

The actual issue was spec-interpretation drift between independent workers (worker-1 used short labels `KIMI:SET` per the spec example; worker-2's tests expected full names `KIMI_API_KEY:SET`). That's a planner-level concern, not a worktree-branching concern.

**Acceptance** (revised):
- D5 confirmed working by independent re-execution of worker-2's tests in its worktree
- No code change needed for W6-A1.1
- Multi-worker spec-interpretation drift queued as Wave 7 candidate

#### A1.2 — Progress events for fallback attempts (~30 min) [DISCOVERED DURING A1]

Found during W6-A1 run 2: when the primary worker engine returns 0 edits, `worker.py:767-815` attempts a fallback dispatch — but no progress events log the attempt. Operators see only the final `step_engine_used` event with `engine_used=<primary>` even when fallback ran (and silently also failed).

**Steps**:
1. Emit `fallback_attempted` progress event when entering the fallback block (with primary + fallback engine names)
2. Emit `fallback_dispatch_result` with success/text_len/error after the dispatch returns
3. Emit `fallback_edits_applied` with count after edit application
4. Emit `fallback_exception` if the dispatch itself raises
5. Add 2 tests covering happy-path fallback and exception-path fallback

**Acceptance**:
- Worker progress jsonl now contains 3 new event types per fallback attempt
- 2 new tests in tests/test_coord_worker.py pass
- Future "did fallback actually run?" questions answerable from the progress log alone

#### A2 — Token tracking real-API validation (~1 hr)

QA + Architect reviewers identified ledger shows `in=0 out=0` despite W4-K wiring. Closes their directives.

**Steps**:
1. Add `tests/test_engines_tokens_live.py` opt-in via `HARNESS_LIVE_TESTS=1` env var
2. Each engine: dispatch 1-line prompt, assert `tokens_in > 0` and `tokens_out > 0` in the response
3. Run once locally with real API; confirm `harness budget summary` shows non-zero numbers
4. Update existing fixture-based tests to use production-shape response stubs

**Acceptance**:
- New live test file exists, passes when `HARNESS_LIVE_TESTS=1`
- `harness budget summary` shows non-zero `in/out` for at least one row per engine
- Commit pushed

#### A3 — Mutation test sweep on top-5 modules (~1.5 hr)

QA directive verbatim. Validates the 1422-test count means something.

**Steps**: For each of `dispatcher.py`, `concrete.py`, `worker.py`, `integrator.py`, `orchestrator.py`:
1. Pick 5 mutations (flip boolean return, corrupt string constant, swap operator, etc.)
2. Apply mutation, run `pytest -q`, count failing tests, restore original
3. Document at `coord/reviews/mutation_sweep_20260523.md`

**Acceptance**:
- Each module has ≥3 tests fail per mutation on average (QA threshold)
- Modules failing the bar get follow-up STATUS rows for real-assertion work
- Mutation sweep report exists in repo

### Phase B — Refactor (fixes structural debt before new engines)

#### B1 — Extract EngineTransport base class (~2 hr)

Architect directive. Eliminates the bug-class that caused W5-V's three SSE bugs.

**Steps**:
1. New `src/harness/engines/transport.py` with `StreamingTransport` base owning:
   - SSE parse loop (both `data: ` and `data:` prefixes)
   - Chunk reassembly
   - `[DONE]` terminator
   - `parse_error_no_chunks` diagnostic
   - Usage extraction
2. Abstract methods: `build_payload(content, model, extra) -> dict`, `endpoint_url() -> str`, `headers() -> dict`
3. Retrofit `KimiConcrete`, `DeepSeekConcrete`, `MiMoConcrete` to subclass
4. Update tests

**Acceptance**:
- ≥80 lines of duplicated SSE parsing consolidated into base class
- All 1422 tests still green
- Adding a new engine requires only payload+endpoint+headers (no SSE re-implementation)

#### B2 — `harness preflight` verb (~1 hr)

Operator Advocate directive. <30s readiness gate.

**Steps**:
1. New CLI verb runs all checks in parallel:
   - Per engine: API key set + 1-token probe succeeds
   - Observer: registered in Task Scheduler
   - STATUS.csv: writable, recent mtime
   - Pytest cache: last run green
   - Git working tree: clean
2. Output: single pass/fail matrix
3. Exit codes: 0 / 1 (warnings) / 4 (L5 blockers)

**Acceptance**:
- Runs in <30s wall clock
- Output fits operator's eye in one screen
- All checks scriptable for CI

#### B3 — Wire preflight as `harness start --mode autonomous` gate (~30 min)

Operator Advocate directive cont'd — "gate orchestrator start behind a green preflight."

**Steps**:
1. `harness start --mode autonomous` runs `harness preflight` first
2. If preflight exit > 0, refuse to install Task Scheduler
3. `--skip-preflight` bypass with stderr warning

**Acceptance**:
- Autonomous mode refuses when any engine is unreachable
- Bypass path works for advanced operators
- Test asserts the gate

### Phase C — Operational hygiene

#### C1 — Fix cross-project stop-hook scope (~30 min)

Hook noise consumed ~25% of prior session.

**Steps**:
1. Edit `D:/Projects/warehouse/.claude/hooks/check-csv-stale.sh`
2. Add a guard: return 0 if `$PWD` is not under `D:/Projects/warehouse`
3. Manual test: cd to xaxiu-harness, save a file, confirm hook does not fire

**Acceptance**:
- Hook silent during xaxiu-harness sessions
- Hook still fires when working inside warehouse

#### C2 — Dispatch-layer "engine dead" alarm (~1 hr)

Operator Advocate finding: dispatch had no signal for "engine returned 0/N across the campaign."

**Steps**:
1. Per-engine rolling success-rate tracked in `coord/dev_loop/state.json`
2. After 5 consecutive failures, emit L4 warning + fire Windows toast (W5-PP infrastructure)
3. Surface dead-engine count in `harness preflight` (B2)

**Acceptance**:
- Simulated 5-in-a-row Kimi failure triggers alarm + toast
- Sub-threshold failure stays silent (no spam)
- Counter resets on first success

### W6-CLOSEOUT

After all 8 tasks pass their MiMo audit gate:
1. Write `coord/reviews/wave-6-closeout.md` summarizing what shipped, mutation sweep results, preflight pass state
2. STATUS.csv row `W6-CLOSEOUT` marked shipped
3. Push final commit
4. **Stop**. Wait for operator review before opening Wave 7.

## What this plan explicitly EXCLUDES

- ❌ Acceptance-criteria auto-validation (deferred idea #1)
- ❌ Weak-spec → DeepSeek upgrade (deferred idea #2)
- ❌ State-machine queue items (deferred idea #6)
- ❌ Dashboard frontend work (W5-LL backend stays as-is)
- ❌ New sample specs / templates
- ❌ Memory entries / README refreshes that aren't validating Wave 6
- ❌ Another brainstorm
- ❌ Any new CLI verb not listed above

If Wave 6 ships clean, those return as Wave 7 candidates. Not before.

## Why this spec exists

The 5-MiMo session review at `coord/reviews/external/20260523T140257Z_*.md` produced 5 directives that collectively pointed at one truth: the harness was over-built relative to what's been validated. Wave 6 corrects that by spending one focused session on validation + foundation + hygiene, with a MiMo audit between every task to catch the same "ship-without-review" pattern from happening again.

This plan supersedes any in-flight feature work. Operator approved 2026-05-23.
