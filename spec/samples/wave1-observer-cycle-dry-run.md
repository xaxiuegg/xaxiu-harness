# wave1-observer-cycle-dry-run — `harness observer cycle --dry-run`

## Context (for the planner)

`harness observer cycle` fires a Kimi-driven audit cycle.  Operators
re-arming the Task Scheduler entry want a way to inspect the prompt
+ inputs *without* actually dispatching, so they can validate the
configuration before letting the scheduler fire it autonomously.

Today the only way to preview is to read the source.  We want a
documented `--dry-run` mode.

## Goal

Add a `--dry-run` flag on `harness observer cycle` that:

1. Resolves all inputs the real run would use (cycle config, prompt
   template, recent-events window, output path).
2. Writes a single JSON file at
   `coord/observer/cycle_dryrun_<utc_iso>.json` containing:
   - `prompt_first_200_chars: str`
   - `prompt_length_chars: int`
   - `engine: str` (would-dispatch)
   - `output_path: str` (would-write)
   - `recent_event_count: int`
3. Prints the path to stdout; exits 0.
4. Makes no engine dispatch, no Kimi network call, no state mutation
   beyond the dryrun file.

## Acceptance

- `python -m pytest tests/test_observer.py -q` stays green.
- 3 new tests:
  1. `--dry-run` writes the expected JSON keys.
  2. `--dry-run` does NOT call the dispatch helper (mock + assert
     `not_called`).
  3. `prompt_first_200_chars` is exactly the first 200 chars of the
     full prompt — no truncation ellipsis, no whitespace folding.

## File scope

- `src/harness/observer/cycle.py` — extend the existing entry point.
  Keep new code under 35 LOC.
- `src/harness/cli.py` — add the `--dry-run` flag to the click verb.
- `tests/test_observer.py` — append the 3 tests.

DO NOT change the real-run path's behaviour.  DO NOT log any DPAPI
secret to the dryrun JSON.
