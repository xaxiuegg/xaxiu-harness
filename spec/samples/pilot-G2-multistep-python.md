# PILOT-G2: multi-step single worker (Python module + matching test)

**Purpose**: Phase B comprehensive — exercise multi-step worker plan
with cross-file edits (source + matching test).

## Goal

A single worker handles two sequential steps:

Step 1: Add a new helper function `_minutes_since(timestamp_iso)` to
`scripts/multi_agent_coverage.py`.  The helper takes an ISO-8601 UTC
timestamp string and returns the number of minutes elapsed as an int.

Step 2: Add a unit test for the new helper in a new file
`tests/test_pilot_g2_helper.py` that imports the function and verifies
basic behaviour (recent timestamp returns small int, old timestamp
returns large int).

## Acceptance

1. `scripts/multi_agent_coverage.py` has a new `_minutes_since(...)`
   function added (alongside the existing helpers, before `def main`).
2. `tests/test_pilot_g2_helper.py` exists with at least 2 test
   functions exercising `_minutes_since`.
3. `python -m py_compile scripts/multi_agent_coverage.py` passes.
4. Existing code in `scripts/multi_agent_coverage.py` is otherwise
   unchanged.

## Why this spec exists

Most production specs require multi-step worker plans (touch multiple
files for one logical change).  G2 proves the harness threads
`step_modified` / `read_set` updates correctly between steps.
