# doctor active-dispatches check (W6-A1 run 5, mimo worker) — surface stuck dispatch state

## Planner guidance (W6-A1 directive)

**This change MUST be done by ONE worker (single `write_set` covering BOTH files) because the tests in `tests/test_doctor.py` depend on the new function in `src/harness/doctor.py`. Splitting across workers causes test failures because workers run in isolated worktrees that don't inherit each other's changes.**

A single worker with `write_set: ["src/harness/doctor.py", "tests/test_doctor.py"]` is the correct shape.

## Context

`harness doctor` ships several preflight checks (python_version, git, dpapi, secrets, engine_reachability, env_var_inventory, coord_writable, task_scheduler). It does NOT surface whether the in-flight dispatch table is healthy. Operators running long autonomous sessions sometimes find `state/active_dispatches.json` accumulates entries from crashed workers that never got cleaned up, masking real engine-utilization signals.

## Goal

Add a new doctor check named `active_dispatches` that:

1. Calls `harness.state.files.read_active_dispatches()` to load the current list.
2. Reports the count of active dispatches.
3. Severity rules:
   - 0 entries → severity `"ok"`, message `"no active dispatches"`
   - 1–3 entries → severity `"ok"`, message like `"2 active dispatches running"`
   - 4 or more → severity `"warn"`, message like `"7 active dispatches — possible stuck workers; check state/active_dispatches.json"`
4. If `read_active_dispatches()` raises (corrupted file), return severity `"warn"` with message like `"active_dispatches.json unreadable: <exc>"` and a `fix` hint suggesting to inspect / repair the file. NEVER let an exception escape — the doctor pass should still complete.
5. Add the new check to `run_all()` so it appears in `harness doctor` output between `env_var_inventory` and `coord_dir`.

## Acceptance

- `pytest tests/test_doctor.py -q` stays green (existing 24 tests must still pass).
- New tests for `_check_active_dispatches` covering:
  - empty list → severity `ok`, message contains `"no active dispatches"`
  - 2 entries → severity `ok`, message contains `"2 active"`
  - 5 entries → severity `warn`, message contains `"5 active"` and the word `"stuck"` (case-insensitive)
  - corrupted JSON → severity `warn`, message contains `"unreadable"`; pytest must not raise
- `harness doctor` output (smoke) shows a new row for `active_dispatches`.
- `_check_active_dispatches` is referenced inside `run_all()` (you can grep for it).

## File scope

- `src/harness/doctor.py` — add `_check_active_dispatches()` (~25 LOC) and include it in `run_all()`. Use a try/except around the read call. Import `harness.state.files` lazily inside the function to avoid touching module-level import order.
- `tests/test_doctor.py` — add 4 new tests. Use `monkeypatch.setattr` or `with patch(...)` to stub `harness.state.files.read_active_dispatches`. Construct `ActiveDispatch` instances using all required fields (`dispatch_id`, `project`, `packet_path`, `backend`, `started_at`, `status`).

The `ActiveDispatch` model (from `harness.state.files`) requires:
- `dispatch_id: str` (UUID)
- `project: str`
- `packet_path: str`
- `backend: Literal["deepseek", "kimi", "anthropic", "gemini", "mimo", "mock"]`
- `started_at: str` (ISO 8601 UTC)
- `status: Literal["running", "complete", "failed", "fallback"]`

Both files modified by ONE worker. Stdlib + existing harness internals only.

## Output format

The worker prompt includes the existing contents of `src/harness/doctor.py` and `tests/test_doctor.py` (W6-A1-3 fix). Emit FILE/REPLACE blocks. For `src/harness/doctor.py`, you may either:

- Anchor a SEARCH block on the existing end-of-file marker `def run_all() -> list[Diagnosis]:` and add the new function ABOVE it + extend the run_all return list, or
- Append the new function with an empty SEARCH and then make a second small REPLACE that adds the call inside `run_all()`.

For `tests/test_doctor.py`, use empty SEARCH to append the 4 new tests at the end of the file.

## Why this spec exists

W6-A1 run 5 — first run of the new spec after retiring the stale env_var_inventory variant (already shipped to master). Runs 1-4 against that stale spec hit silent_no_op or partial edits because there was no real work to do; this spec adds a check that is genuinely missing, exercising the W6-A1-3 write_set-context fix end-to-end.
