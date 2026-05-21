# Packet: proxy/state.py coverage uplift + edge-case tests

## Mission

`src/harness/proxy/state.py` shipped with basic schema + roundtrip tests but several edge cases are under-covered: missing keys, schema-version migration, atomic-write contract details, and corrupt-file recovery. Bring coverage to ≥95% on the module.

Test-only packet. Disjoint from in-flight work.

## In-scope MODIFY files

- `tests/test_proxy_state.py` — extend with edge-case tests

## In-scope NEW files

NONE.

## Test additions

For `src/harness/proxy/state.py`:

1. KeyState rejects negative `in_flight` (already covered? if so, ensure max_concurrent edge: 0 → ValueError or just int constraint check)
2. KeyState rejects `key_alias` violating the regex pattern (`^[a-z][a-z0-9_-]{0,31}$`)
3. KeyState rejects `circuit_state` not in {closed, half_open, open}
4. ProxyState rejects unknown top-level field (extra="forbid")
5. ProxyState with empty keys dict — valid, returns model with `len(state.keys) == 0`
6. `read_state` on missing file — behavior (depends on impl; probably raises FileNotFoundError or returns default)
7. `read_state` on corrupted JSON — depends on impl; test the documented behavior
8. `write_state` atomic contract — mock `os.replace` to raise; original file unchanged
9. Round-trip of complex state (multiple keys, varied circuit_states) preserves all fields
10. `recent_outcomes` enforces max_length=20 (truncation or rejection)
11. KeyState's `cooldown_until` field accepts iso-8601 strings and None

Target ≥9 new tests. Final coverage on proxy/state.py should be ≥95%.

## Acceptance criteria

1. `pytest tests/test_proxy_state.py -q` shows green.
2. `pytest --cov=src/harness/proxy/state --cov-report=term tests/test_proxy_state.py` reports ≥95%.
3. `pytest tests/ -q` shows full suite green.
4. Single commit: `test(proxy): state.py edge-case coverage uplift (95%+)`.

## Reference

- `src/harness/proxy/state.py` — module being tested
- `tests/test_proxy_state.py` — existing test file

## Output format

1 test-file extension + 1 commit. No source code changes.
