# Packet: Wave B/2.state-files — boundary tests for state/files.py

## Mission

Push `src/harness/state/files.py` coverage from 39% to >60%. The module handles JSON state files (engine health, active dispatches, routing).

## In-scope (NEW file only)

`tests/test_state_files.py` — single new test file. NO modifications to `src/harness/state/files.py`.

## Required test coverage

Read `src/harness/state/files.py` for the public API. Cover at minimum:

1. **Engine health roundtrip** — `update_engine_health(engine, healthy=True, latency_ms=42)` then `read_engine_health()` returns the engine's entry with those values.
2. **Engine health pruning** — entries older than the documented retention threshold are removed on read.
3. **Active dispatch insert/update/remove** — round-trip via the relevant functions.
4. **Atomic write** — verify tempfile + `os.replace` pattern is used (mock `tempfile.mkstemp` and `os.replace`).
5. **Mode 0600 after write** — verify `os.chmod` is called with 0o600 (on Windows it's advisory per ACCEPTED_LIMITATIONS::ACCEPT-1; assertion still verifies the call happened).
6. **Schema validation** — passing an unexpected field raises `SchemaViolation` (per Wave A.6 retrofit; check what's actually wired).
7. **First-read with missing file** — returns sensible default (empty dict / empty list), does NOT raise.
8. **Concurrent-write race** — best-effort: two `update_engine_health` calls in quick succession both land (use threading.Thread, soft-assert).

Use `tmp_path` fixture for the state directory; patch `STATE_DIR` to `tmp_path` so tests don't touch the real state file.

## Acceptance criteria

1. `python -m pytest tests/ -q` shows ≥185 + new tests, all green.
2. `python -m pytest tests/test_state_files.py --cov=src/harness/state/files --cov-report=term-missing` shows >60% coverage.
3. No modifications to any file outside `tests/test_state_files.py`.
4. Single commit: `test(state/files): boundary tests (Wave B/2.state-files)`.

## Reference

- `src/harness/state/files.py` — read first to enumerate functions and dataclasses
- `src/harness/errors.py::SchemaViolation` — raised on closed-schema violation
- `src/harness/_constants.py::STATE_DIR` — patch target for tmp_path redirection

## Output format

Single new file at `tests/test_state_files.py`. No modifications elsewhere.
