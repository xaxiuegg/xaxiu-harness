# Packet: loops/supervisors.py coverage uplift (40% → ≥75%)

## Mission

`src/harness/loops/supervisors.py` ships the 4 productized supervisors (CreativitySupervisor, DevelopingSupervisor, IntegratingSupervisor, ProcessImprovementSupervisor) at 40% coverage. The 60% gap is mostly the engine-dispatch paths. Bring coverage to ≥75% by adding tests that mock `harness.engines.dispatcher.dispatch_packet` and exercise each supervisor's happy path + failure path + engine="claude-in-session" no-op path.

Test-only packet. No source code changes.

## In-scope MODIFY files

- `tests/test_loops_supervisors.py` — extend with per-supervisor coverage

## In-scope NEW files

NONE.

## Test additions

For each of the 4 supervisors:

**CreativitySupervisor (engine="claude-in-session" branch)**:
1. With engine="claude-in-session", returns SupervisorResult with `state_diff == {}` and `log_summary` mentioning "claude-in-session" or "needs external engine"
2. With engine="swarm/kimi" (mocked dispatch returns valid JSON): parses ideas, queues top-scored above threshold

**DevelopingSupervisor**:
3. No eligible wave (wave_plan empty or all deps unmet): returns no-op SupervisorResult
4. With one eligible wave and existing packet file: emits "would dispatch" or fires dispatch (mocked subprocess.Popen)
5. With active_dispatches already containing a developing-phase entry: no-op (don't double-dispatch)

**IntegratingSupervisor**:
6. With HARNESS_ALLOW_AUTO_COMMIT unset: validates but does NOT call git commit (mock subprocess to count git calls)
7. With pending_merges containing a block_commit:True entry: skips that entry
8. With pytest mocked to return failure: writes the failure into state_diff, does not commit

**ProcessImprovementSupervisor**:
9. With engine="claude-in-session": no-op (same pattern as CreativitySupervisor)
10. With engine="kimi" mocked: parses findings into P1/P2/P3 tiers; populates state_diff with findings_log

Target ≥10 new tests; final supervisors.py coverage ≥75%.

## Acceptance criteria

1. `pytest tests/test_loops_supervisors.py -q` shows green (all new + existing).
2. `pytest --cov=src/harness/loops/supervisors --cov-report=term tests/test_loops_supervisors.py` reports ≥75%.
3. `pytest tests/ -q` shows full suite green.
4. Single commit: `test(supervisors): per-supervisor coverage uplift (40% → ≥75%)`.

## Reference

- `src/harness/loops/supervisors.py` — module being tested
- `tests/test_loops_supervisors.py` — existing tests (extend)
- `src/harness/engines/dispatcher.py::dispatch_packet` — mock target

## Output format

1 test-file extension + 1 commit. No source code changes.
