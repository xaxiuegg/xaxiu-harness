# Packet: DevelopingSupervisor + IntegratingSupervisor coverage (narrow retry, part 2)

## Mission

Prior Round 16 supervisors packet timed out (too broad). Splitting: this packet covers DevelopingSupervisor + IntegratingSupervisor only.

Test-only. No source changes.

## In-scope MODIFY files

- `tests/test_loops_supervisors.py` — add `TestDevelopingSupervisor` + `TestIntegratingSupervisor` classes

## Test additions

**DevelopingSupervisor**:

1. Empty wave_plan: returns no-op SupervisorResult
2. wave_plan has queued wave with all deps met + existing packet at coord/packets/<id>/packet.md: emits dispatch (mock subprocess.Popen, assert called with `xaxiu-swarm dispatch` args)
3. active_dispatches already has a phase="developing" entry: no-op (don't double-dispatch)
4. wave_plan has queued wave but deps not met: skipped

**IntegratingSupervisor**:

5. With HARNESS_ALLOW_AUTO_COMMIT unset (default): validates but does NOT commit; mock subprocess to count `git commit` calls = 0
6. With HARNESS_ALLOW_AUTO_COMMIT="true" and pytest mock returns 0: invokes `git add` + `git commit` (verified via mock)
7. pending_merges contains entry with `block_commit: true`: skips that entry, does not commit
8. pytest mock returns non-zero (regression): writes failure into state_diff, no commit

Use `patch("harness.loops.supervisors.subprocess.run")` and `patch("harness.loops.supervisors.subprocess.Popen")` as needed.

Target ≥7 new tests.

## Acceptance criteria

1. `pytest tests/test_loops_supervisors.py -q` green.
2. `pytest tests/ -q` shows full suite green.
3. Single commit: `test(supervisors): DevelopingSupervisor + IntegratingSupervisor coverage`.

## Reference

- `src/harness/loops/supervisors.py::DevelopingSupervisor, IntegratingSupervisor`
- `tests/test_loops_supervisors.py` — extend

## Output format

1 test-file extension + 1 commit. ≤120 LOC of test additions.
