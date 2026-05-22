# wave1-doctor-no-engine-warn — `harness doctor` warns when zero engine keys set

## Context (for the planner)

`harness doctor` runs an env-var inventory check (per
`spec/samples/env-doctor-check.md`, shipped 2026-05-22 commit 073aebb).
The inventory already reports `severity=warn` when *all* keys are unset.

There is no separate check that surfaces "no engine reachable" at a
higher signal level than the noisy env-var inventory line.  On a fresh
clone where the operator hasn't yet stored DPAPI secrets or exported
env vars, the doctor still reports `overall: OK` because the inventory
is `warn`, not `fail`, and every other check passes.

A non-technical operator scanning the green/yellow/red bar will read
"OK" and dispatch — only to discover at first `coord run` that no
engine is configured.  We want a dedicated check that turns red when
*both* DPAPI and env vars are empty, so the doctor's `overall` flips
to `fail` and the wizard hint fires.

## Goal

Add a new doctor check `engine_reachability` that:

1. Inspects DPAPI-stored engine keys via the
   `harness.secrets.dpapi.list_secrets` helper (any non-empty list passes).
2. Inspects env vars `KIMI_API_KEY`, `DEEPSEEK_API_KEY`,
   `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (any one non-empty passes).
3. If neither source has any key → severity `"fail"` with a fix line
   pointing at `harness install` and the env-var-export hint.
4. If at least one key is reachable → severity `"ok"` with a message
   summarising which source (e.g. `"dpapi=2 env=KIMI_API_KEY"`).
5. Wired into `run_all()` between `_check_secrets` and
   `_check_env_var_inventory`.

## Acceptance

- `python -m pytest tests/test_doctor.py -q` stays green.
- 4 new tests cover: both sources empty → fail, only DPAPI → ok,
  only env → ok, both populated → ok.
- `harness doctor` `overall` flips to `fail` when no engine reachable.
- The fix line never echoes any env-var value.

## File scope

- `src/harness/doctor.py` — add `_check_engine_reachability()` and
  insert it into `run_all()`.  Keep new code under 35 LOC.
- `tests/test_doctor.py` — add the 4 tests; reuse the existing
  `monkeypatch` + `patch("harness.secrets.dpapi.list_secrets", ...)`
  pattern from `_check_secrets` tests.

DO NOT modify any other module.  Stdlib + existing harness internals
only.  NEVER print actual key values.
