# Packet: CreativitySupervisor coverage (narrow retry)

## Mission

Prior Round 16 dispatch tried to cover ALL FOUR supervisors at once and timed out. Splitting: this packet covers CreativitySupervisor only. ~5 tests targeting the engine="claude-in-session" no-op path + engine="swarm/kimi" mocked-dispatch path + parsing edge cases.

Test-only. No source changes.

## In-scope MODIFY files

- `tests/test_loops_supervisors.py` — add a `TestCreativitySupervisor` class

## In-scope NEW files

NONE.

## Test additions

For `CreativitySupervisor`:

1. With engine="claude-in-session" and minimal state: returns SupervisorResult with empty state_diff and a log_summary mentioning "claude-in-session" or "needs external engine"
2. With engine="swarm/kimi" + mocked dispatch_packet returning a valid JSON array of 2 ideas (both scoring > 60): adds top-scored to phase_cursors.creativity.queue in state_diff
3. With engine="swarm/kimi" + mocked dispatch returning ideas all scoring < threshold 60: does NOT queue any
4. With engine="swarm/kimi" + dispatch returns success=False: emits SupervisorResult with escalation (level L3)
5. With engine="swarm/kimi" + dispatch returns malformed JSON: graceful — no exception, log_summary explains, no state_diff
6. write_set contains "phase_cursors.creativity" when work is done

Use `from unittest.mock import patch` to mock `harness.engines.dispatcher.dispatch_packet`.

Target ≥5 new tests. Coverage on CreativitySupervisor lines should approach 100%.

## Acceptance criteria

1. `pytest tests/test_loops_supervisors.py -q` green.
2. `pytest tests/ -q` shows full suite green.
3. Single commit: `test(supervisors): CreativitySupervisor coverage (narrow retry)`.

## Reference

- `src/harness/loops/supervisors.py::CreativitySupervisor` — class under test
- `tests/test_loops_supervisors.py` — existing tests (extend)

## Output format

1 test-file extension + 1 commit. ≤80 LOC of test additions.
