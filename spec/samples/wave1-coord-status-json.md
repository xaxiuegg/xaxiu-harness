# wave1-coord-status-json — `harness coord status --json` machine-readable output

## Context (for the planner)

`harness coord status --run-id <rid>` currently prints a human-readable
summary of `runs/<rid>/run_state.json`.  Dashboards and external
schedulers want a JSON variant that matches the `RunState` schema so
they don't have to re-parse the text.

The `RunState` pydantic model already lives in
`src/harness/coord/schemas.py`.  `model_dump_json()` is the canonical
serialiser.

## Goal

Add a `--json` flag to `harness coord status` that:

1. When set, prints the full `RunState` as compact JSON to stdout and
   exits 0 if the run state was readable, 1 if not.
2. When omitted, preserves the existing human-readable behaviour
   byte-for-byte.
3. Documents both modes in the click help string.

## Acceptance

- `python -m pytest tests/test_coord_cli.py -q` stays green.
- 3 new tests via `CliRunner`:
  1. `coord status --run-id X --json` returns parseable JSON whose
     `run_id` and `state` match the on-disk file.
  2. `coord status --run-id X` (no flag) still produces the human
     output (assert one expected substring like `state:`).
  3. `coord status --run-id NONEXISTENT --json` exits 1 and emits
     `{"error": "..."}` on stdout (still valid JSON for the consumer).

## File scope

- `src/harness/cli.py` — add `--json` flag on the `coord status`
  click command.  Keep new code under 25 LOC.
- `tests/test_coord_cli.py` — append the 3 tests.

DO NOT change the human-readable format.  DO NOT touch the RunState
schema.
