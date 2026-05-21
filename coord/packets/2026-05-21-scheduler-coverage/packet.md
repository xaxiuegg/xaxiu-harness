# Packet: scheduler.py coverage uplift (32% → ≥75%)

## Mission

`src/harness/loops/scheduler.py` and `src/harness/observer/scheduler.py` both ship the Windows Task Scheduler PowerShell-script-generator logic with only 32% test coverage. Tests currently mock the subprocess at the outermost call site, but the PowerShell-script-construction helpers (`_build_register_script`, `_pwsh`, `_loop_tick_cmd`, etc.) have no direct tests.

Add focused unit tests so the coverage rises to ≥75% on both modules without changing production code.

## In-scope MODIFY files

- `tests/test_loops_scheduler.py` — extend with helper-function tests
- `tests/test_observer.py` — extend the scheduler section (it's a big test file; just add to the bottom)

## In-scope NEW files

NONE.

## Test additions

For `src/harness/loops/scheduler.py`:

1. `_pwsh()` — happy path returns 'pwsh' or 'powershell' from `shutil.which` (mock both possibilities)
2. `_pwsh()` — returns None when neither is on PATH
3. `_loop_tick_cmd()` — returns expected string with venv python path when `.venv/Scripts/python.exe` exists (mocked Path.exists)
4. `_loop_tick_cmd()` — falls back to plain `python` when no venv
5. `_build_register_script(cadence_minutes)` — contains `RepetitionInterval (New-TimeSpan -Minutes {N})` with the input N
6. `_build_register_script` — contains `try { ... } catch { ... }` block (proves error-stop wrapper is present)
7. `_build_register_script` — uses `-RunLevel Limited` (no admin needed)
8. `register_loop_task` — propagates returncode != 0 as `(False, error_msg)`
9. `unregister_loop_task` — handles the "task not found" case (returns success with "not found" message)

For `src/harness/observer/scheduler.py`:

10. `_build_ps_script` — task name interpolation works (no shell injection from name)
11. `register_tasks` — independently reports cycle vs retro success in mixed-success cases
12. `unregister_tasks` — iterates both task names, returns combined report

Target ≥10 new tests. Aim for ≥75% coverage on both scheduler modules.

## Acceptance criteria

1. `pytest --cov=src/harness/loops/scheduler --cov=src/harness/observer/scheduler -q` shows ≥75% on each module.
2. No production code changes; only tests.
3. `pytest tests/ -q` shows green overall.
4. Single commit: `test(scheduler): coverage uplift for loops + observer scheduler helpers (32% → ≥75%)`.

## Reference

- `src/harness/loops/scheduler.py` — module being tested
- `src/harness/observer/scheduler.py` — sibling module
- `tests/test_loops_scheduler.py` — existing tests (mocked subprocess)
- `tests/test_observer.py` — existing observer scheduler tests

## Output format

2 test-file extensions + 1 commit. No source-code changes.
