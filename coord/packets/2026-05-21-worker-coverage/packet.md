# Packet: coord/worker.py coverage uplift (73% → ≥90%)

## Mission

`src/harness/coord/worker.py` is the v2 execution engine — runs one WorkerTask in its isolated worktree, writes checkpoints, emits a WorkerResult. Currently at 73% coverage; uncovered paths are mostly the resume-from-checkpoint branches, error paths, and the pytest summary parsing edge cases.

Test-only packet. No source code changes.

## In-scope MODIFY files

- `tests/test_coord_worker.py` — extend with branch-coverage tests

## In-scope NEW files

NONE.

## Test additions

For `run_worker`:

1. Fresh task with no resume_from + no existing checkpoint: creates initial Checkpoint with state="in_progress"
2. Resume from existing checkpoint (last_completed_step_index = 2 of 5 steps): processes only steps 3-5
3. Resume from completed checkpoint: should still emit a WorkerResult; tests are re-run for verification
4. Task with empty `test_set`: skips pytest, returns ran=0/passed=0/failed=0
5. pytest returns 0 with "1 passed" in stdout: parses correctly
6. pytest returns 1 with "3 failed" in stdout: WorkerResult state=="failed", error_tag set
7. pytest returns 2 (error) — distinct from failed; state still classifies as "failed" with diagnostic
8. pytest timeout (mock subprocess.run to raise TimeoutExpired): caught + reported in result.diagnostic
9. Worktree missing (worktree_path doesn't exist) — graceful error path
10. Deliverable JSON written to runs/<id>/deliverables/<wid>.json with correct schema fields

For `_run_pytest`:

11. Returns expected dict shape from "N passed" / "N failed" / "N skipped" regex matches
12. Returns zeros when none of those phrases present (empty pytest output)

Target ≥10 new tests. Final coord/worker.py coverage ≥90%.

## Acceptance criteria

1. `pytest tests/ -q` green.
2. `pytest --cov=src/harness/coord/worker --cov-report=term` reports ≥90%.
3. Single commit: `test(coord.worker): branch coverage uplift (73% → ≥90%)`.

## Reference

- `src/harness/coord/worker.py` — module being tested
- `tests/test_coord_worker.py` — existing tests (extend)

## Output format

1 test-file extension + 1 commit. No source code changes.
