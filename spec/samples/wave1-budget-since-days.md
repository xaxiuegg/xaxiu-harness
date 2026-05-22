# wave1-budget-since-days — `harness budget summary --since-days N`

## Context (for the planner)

`harness budget summary` accepts `--since-iso YYYY-MM-DDTHH:MM:SSZ`.
The operator typically asks "what have I spent in the last 7 days?"
and has to compute the ISO timestamp by hand each time.

`harness.budget.summary()` already accepts a `since_iso` argument; we
just need a CLI ergonomic on top.

## Goal

Add a `--since-days N` option to `harness budget summary` that:

1. When provided, computes `now_utc - N days` as the ISO cutoff and
   passes it down as `since_iso`.
2. Is mutually exclusive with `--since-iso` (click `nargs` / manual
   guard); if both are passed, error with exit 2 + a click usage error.
3. Validates `N >= 1`; reject `0` and negative with click `BadParameter`.

## Acceptance

- `python -m pytest tests/test_budget.py -q` stays green.
- 4 new tests via `CliRunner`:
  1. `--since-days 1` filters entries to the last day.
  2. `--since-days 30` includes a 29-day-old entry but excludes a
     31-day-old one.
  3. Both `--since-iso` and `--since-days` → exit 2 with usage error.
  4. `--since-days 0` → exit 2 with `BadParameter`.

## File scope

- `src/harness/cli.py` — extend the existing `budget summary` click
  command.  Keep new code under 30 LOC.
- `tests/test_budget.py` — append the 4 tests.

DO NOT add new pricing rows.  DO NOT touch `harness.budget.summary()`
internals — only the CLI layer.
