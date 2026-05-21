# Packet: heartbeat.py coverage uplift + edge-case tests

## Mission

`src/harness/heartbeat.py` shipped with 16 tests, but several internal helpers and edge cases are under-covered. Bring coverage to ≥95% on the module by adding focused unit tests for: bad-ISO timestamps in `_age_seconds`, missing state.json fields, signal-derivation from edge-case state shapes, and the `format_for_human` STALE prefix boundary.

Test-only packet. No production code changes. Disjoint from any other in-flight work.

## In-scope MODIFY files

- `tests/test_heartbeat.py` — extend with edge-case tests

## In-scope NEW files

NONE.

## Test additions

For `src/harness/heartbeat.py`:

1. `_age_seconds` with `pulsed_at` already in `%Y-%m-%dT%H:%M:%S.%fZ` format (microseconds) — should parse correctly via fromisoformat path
2. `_age_seconds` with offset-aware ISO (`2026-05-21T01:00:00+00:00`) — parses correctly
3. `_age_seconds` with malformed string — raises ValueError (caller's responsibility, but document the contract via test)
4. `_safe_int` returns 0 on None, on non-numeric string, on float
5. `_engine_inflight` with missing engine_slots key returns 0
6. `_engine_inflight` with engine_slots[name] = non-dict returns 0
7. `_engine_inflight` with in_flight as a string (not list) returns 0
8. `_last_escalation_id` with empty escalations returns None
9. `_last_escalation_id` with non-dict last entry returns None
10. `pulse()` with state missing every optional field still returns valid Heartbeat (all defaults applied)
11. `format_for_human` with `stale_after_seconds=0` always marks stale
12. `format_for_human` with beat 60s old + `stale_after_seconds=60` is exactly on the boundary — test the inclusive/exclusive semantics

Target ≥10 new tests. Final coverage on heartbeat.py should be ≥95%.

## Acceptance criteria

1. `pytest tests/test_heartbeat.py -q` shows green.
2. `pytest --cov=src/harness/heartbeat --cov-report=term tests/test_heartbeat.py` reports ≥95% line coverage.
3. `pytest tests/ -q` shows full suite green (no regressions).
4. Single commit: `test(heartbeat): edge-case coverage uplift (95%+ on heartbeat.py)`.

## Reference

- `src/harness/heartbeat.py` — module being tested
- `tests/test_heartbeat.py` — existing test file (extend it)

## Output format

1 test-file extension + 1 commit. No source code changes.
