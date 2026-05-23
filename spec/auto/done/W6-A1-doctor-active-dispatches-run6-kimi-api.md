# doctor active-dispatches check (W6-A1 run 6, kimi-api worker) — surface stuck dispatch state (verify-only retry)

## Planner guidance (W6-A1 directive)

**This change MUST be done by ONE worker (single `write_set` covering BOTH files). The tests depend on the implementation.**

A single worker with `write_set: ["src/harness/doctor.py", "tests/test_doctor.py"]` is the correct shape.

## Context

Run 5 (mimo primary → deepseek fallback) successfully shipped `_check_active_dispatches` to master. This run verifies the same flow works when `swarm/kimi-api` is the primary worker engine.

**Important**: master ALREADY contains `_check_active_dispatches` from run 5's commit. The kimi-api worker should detect this and either (a) produce a no-op (acceptable — tests will pass as they already exist) OR (b) refine the implementation (also acceptable as long as tests stay green).

## Goal

This run validates the W6-A1-3 write_set context fix works on kimi-api as primary (not just fallback). Acceptance is tests_passed=true; whether the worker makes any new edits is secondary.

If the worker decides no work is needed (because the function already exists), it should still produce SOME valid output — e.g., a minor docstring tweak, a test reordering, or a single comment — to exercise the prompt-build + edit-apply pipeline.

## Acceptance

- `pytest tests/test_doctor.py -q` stays green.
- Worker reaches `state=completed` with `tests_passed=true`.
- The new run's `runs/<id>/checkpoints/worker-1.json` is preserved as evidence.

## File scope

- `src/harness/doctor.py` and/or `tests/test_doctor.py` (engine may also choose to make no edits if the function is already perfect).

## Output format

Emit FILE/REPLACE blocks for any edits. If no edits are warranted, emit a tiny no-op edit (e.g., add a one-line comment) so the pipeline can apply at least one file change. The W4-A silent_no_op guard requires ≥1 file modified when target_files is declared.

## Why this spec exists

W6-A1 run 6 — kimi-api primary variant. Demonstrates the W6-A1-3 write_set context fix lets kimi-api produce valid output (run 4 against the stale env_var_inventory spec only edited tests, skipped doctor.py).
