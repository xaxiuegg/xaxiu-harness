# doctor active-dispatches check (W6-A1 run 7, deepseek primary) — verify deepseek primary path

## Planner guidance (W6-A1 directive)

**This change MUST be done by ONE worker (single `write_set` covering BOTH files). The tests depend on the implementation.**

A single worker with `write_set: ["src/harness/doctor.py", "tests/test_doctor.py"]` is the correct shape.

## Context

Runs 5 and 6 successfully shipped `_check_active_dispatches` via mimo→deepseek fallback (run 5) and kimi-api primary (run 6). This run validates the same flow works when `swarm/deepseek` is the primary worker engine (not via fallback).

**Important**: master may already contain `_check_active_dispatches` from a prior run's merge. The deepseek worker should detect this and either (a) produce a no-op (acceptable — tests pass as they exist) OR (b) refine the implementation (also acceptable as long as tests stay green).

## Goal

Demonstrate the W6-A1-3 write_set context fix works on deepseek as primary. Acceptance is tests_passed=true.

## Acceptance

- `pytest tests/test_doctor.py -q` stays green.
- Worker reaches `state=completed` with `tests_passed=true`.
- `runs/<id>/checkpoints/worker-1.json` preserved as evidence.

## File scope

- `src/harness/doctor.py` and/or `tests/test_doctor.py` — engine may emit a small no-op edit (e.g., docstring or comment) if the function already exists and is correct.

## Output format

Emit FILE/REPLACE blocks for any edits. The W4-A silent_no_op guard requires ≥1 file modified when target_files is declared, so emit at least one minor edit (a one-line comment is fine).

## Why this spec exists

W6-A1 run 7 — deepseek primary variant. Closes the W6-A1 acceptance ("3 separate runs, each tests_passed=true") with engines exercised: mimo+deepseek-fallback (run5), kimi-api (run6), deepseek (run7).
