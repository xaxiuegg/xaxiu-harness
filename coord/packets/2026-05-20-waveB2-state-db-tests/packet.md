# Packet: Wave B/2.state-db — boundary tests for state/db.py

## Mission

Push `src/harness/state/db.py` coverage from 37% to >60%. The module is the SQLite history store.

## In-scope (NEW file only)

`tests/test_state_db.py` — single new test file. NO modifications to `src/harness/state/db.py`.

## Required test coverage

Read `src/harness/state/db.py` for the public API. Cover at minimum:

1. **`init_db()`** in an empty directory creates the SQLite file with expected tables; second call is idempotent.
2. **`get_connection()` before `init_db()`** → raises `RuntimeError` ("not initialised").
3. **Dispatch history insert/query** — insert a row via the documented helper, query it back via the documented helper, verify the round-trip.
4. **Project name validation** — passing an invalid project name (regex mismatch) → raises `ValueError` (uses `PROJECT_NAME_REGEX`).
5. **Source / action validation** — passing an unknown source or action → raises `ValueError`.
6. **Limit coercion** — passing a string like `"50"` is coerced to int 50; passing `0` clamps to 1; passing `999999` clamps to `LIMIT_MAX`.
7. **Routing change insert** — verify the call records LOCK/BURST/priority change rows.
8. **Concurrent-read safety** — open two connections to the same DB, both see committed inserts (best-effort smoke).

Use `tmp_path` fixture; patch the SQLite path to a temp file so tests are isolated.

## Acceptance criteria

1. `python -m pytest tests/ -q` shows ≥185 + new tests, all green.
2. `python -m pytest tests/test_state_db.py --cov=src/harness/state/db --cov-report=term-missing` shows >60% coverage.
3. No modifications to any file outside `tests/test_state_db.py`.
4. Single commit: `test(state/db): boundary tests (Wave B/2.state-db)`.

## Reference

- `src/harness/state/db.py` — read first
- `src/harness/_constants.py::PROJECT_NAME_REGEX, LIMIT_MAX`

## Output format

Single new file at `tests/test_state_db.py`. No modifications elsewhere.
