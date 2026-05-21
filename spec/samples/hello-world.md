# Sample spec — hello-world (V2-SAMPLE-SPEC)

A minimal markdown spec used by the v2 smoke test (`tests/test_coord_smoke_e2e.py`).
Planner + MockEngine decompose this into a single-worker plan that creates
`mock-out-1.txt` with the canned content.

## Goal

Produce one tiny artifact at the repo root so the operator can verify the
full v2 pipeline (planner → coordinator → worker → integrator) ran end to
end without spending API quota.

## Acceptance

- A single file `mock-out-1.txt` exists in the worker's worktree.
- Its contents read `hello from MockEngine`.
- A checkpoint at `runs/<run_id>/checkpoints/worker-1.json` reports
  `state: "completed"` and `tests_passed: true`.

## Why this spec exists

It is the smallest possible WavePlan that exercises:

1. **Planner stub** — MockEngine emits a valid WavePlan JSON.
2. **Coordinator** — reads plan, creates worktree, dispatches worker.
3. **Worker** — builds a FILE/REPLACE prompt, dispatches via mock engine,
   applies edits, commits, writes checkpoint.
4. **Integrator** — merges the worker branch back to base (optional in
   the smoke test).

If this spec passes, the v2 architecture works.
