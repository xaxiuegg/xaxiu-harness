# Packet: Wave B/2.cli-helpers — boundary tests for cli_helpers.py

## Mission

Push `src/harness/cli_helpers.py` coverage from 28% to >70%. The module is small (25 stmts) so a focused test file gets there quickly.

## In-scope (NEW file only)

`tests/test_cli_helpers.py` — single new test file. NO modifications to `src/harness/cli_helpers.py`.

## Required test coverage

Read `src/harness/cli_helpers.py` for the public functions. Currently contains `probe_all_engines()` and any shared CLI helpers. Cover at minimum:

1. **`probe_all_engines` success path** — patch `httpx.head` (or whatever the function uses for the probe) to return 200 for all three engines (kimi, deepseek, anthropic). Verify the returned health dict has all three entries marked healthy.
2. **`probe_all_engines` partial failure** — patch one engine's probe to raise `httpx.ConnectError`; verify result marks that one unhealthy, others healthy.
3. **`probe_all_engines` all fail** — all probes raise; result shows all unhealthy, function does NOT raise.
4. **`probe_all_engines` timeout** — patch to raise `httpx.TimeoutException`; result marks engine unhealthy.
5. **Latency measurement** — verify the function records elapsed time per probe (within tolerance, e.g. monkeypatch `time.monotonic`).

Any other public helpers in the module: add one happy-path + one error-path test each.

## Acceptance criteria

1. `python -m pytest tests/ -q` shows ≥185 + new tests, all green.
2. `python -m pytest tests/test_cli_helpers.py --cov=src/harness/cli_helpers --cov-report=term-missing` shows >70% coverage.
3. No modifications to any file outside `tests/test_cli_helpers.py`.
4. Single commit: `test(cli_helpers): boundary tests (Wave B/2.cli-helpers)`.

## Reference

- `src/harness/cli_helpers.py` — read first (it's small)
- `tests/test_engines_concrete_boundary.py` — pattern for httpx mocking

## Output format

Single new file at `tests/test_cli_helpers.py`. No modifications elsewhere.
