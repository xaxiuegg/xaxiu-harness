# Packet: Wave B/2.state-jsonl — boundary tests for state/jsonl_log.py

## Mission

Push `src/harness/state/jsonl_log.py` coverage from 22% (lowest in repo) to >60%. The module is the closed-schema JSONL writer with redaction + rotation.

## In-scope (NEW file only)

`tests/test_state_jsonl_log.py` — single new test file. NO modifications to `src/harness/state/jsonl_log.py`.

## Required test coverage

Read `src/harness/state/jsonl_log.py` for the function signatures. Cover at minimum:

1. **`write_log_entry` happy path** — write one entry with valid fields; read the JSONL file, parse the line, verify exactly the 8 expected keys are present.
2. **`write_log_entry` rejects bad outcome** — passing `outcome="not_a_real_outcome"` raises `SchemaViolation` (Wave A.6 retrofit; level=L4).
3. **`write_log_entry` rejects bad backend** — passing `backend="not_a_backend"` raises `SchemaViolation`.
4. **`write_log_entry` rejects bad project name** — invalid regex match raises `SchemaViolation`.
5. **`_redact` matches all 5 patterns** — feed a string containing `sk-abc...`, `Bearer xyz...`, `api_key=...`, `ms-...`, `deepseek-...` and verify each gets replaced with `[REDACTED]`.
6. **`_redact` leaves clean text alone** — feed "Hello world" → returns unchanged.
7. **`rotate_if_needed` no-op below threshold** — small log file (1KB) does not rotate.
8. **`rotate_if_needed` rotates at 100MB** — patch `os.path.getsize` to return 100MB+1; verify file is gzipped to `engine_performance_log.<YYYY-MM>.jsonl.gz` and original is reset to empty.
9. **Atomic append** — verify file is opened in `"ab"` mode (mock `open` and assert mode arg).

Use `tmp_path` and patch `STATE_DIR` to it.

## Acceptance criteria

1. `python -m pytest tests/ -q` shows ≥185 + new tests, all green.
2. `python -m pytest tests/test_state_jsonl_log.py --cov=src/harness/state/jsonl_log --cov-report=term-missing` shows >60% coverage.
3. No modifications to any file outside `tests/test_state_jsonl_log.py`.
4. Single commit: `test(state/jsonl_log): boundary tests (Wave B/2.state-jsonl)`.

## Reference

- `src/harness/state/jsonl_log.py` — read first
- `src/harness/errors.py::SchemaViolation` — L4 error raised
- Memory `feedback_no_env_value_leak_in_shell_checks` — context on why redaction is load-bearing

## Output format

Single new file at `tests/test_state_jsonl_log.py`. No modifications elsewhere.
