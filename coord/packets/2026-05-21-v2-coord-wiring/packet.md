# Packet: v2 coord wiring — unblock first real `harness coord run`

## Mission

The v2 production-readiness audit found 4 CRITICAL gaps in `src/harness/coord/` that together prevent `harness coord run` from actually doing anything. Fix all 4 in a single coord/ packet:

1. **`coord work` CLI is a literal stub** (`cli.py:1266-1271`): prints "pending v2/C implementation" instead of calling `run_worker`. Coordinator.launch_workers spawns subprocesses pointed at this stub, so workers "succeed" instantly with no checkpoint.
2. **`worker.run_worker` never invokes an engine** (`coord/worker.py:74-91`): for-each-step loop only writes a checkpoint; no prompt build, no dispatch, no edit application, no commit. `engine=` parameter unused.
3. **No worktree is ever created** (`coordinator.py:108-143`): `create_worktree` exists but nothing in `launch_workers` calls it. First worker dies with `FileNotFoundError` on the worktree path.
4. **Coordinator looks for checkpoints in wrong directory** (`coordinator.py:104,114,150`): reads `run_dir/<worker>.json` but worker writes to `run_dir/checkpoints/<worker>.json`. Coord never sees workers as completed.

Single packet, all coord/ + cli.py coord-group. Disjoint from engine-via-proxy (different package) and mock-engine (new file).

## In-scope MODIFY files

- `src/harness/coord/coordinator.py` — `launch_workers` creates worktrees before spawning Popen; `poll_workers` reads `run_dir/checkpoints/*.json`
- `src/harness/coord/worker.py` — `run_worker` per-step: build prompt (read_set + step.instruction), call `harness.engines.dispatcher.dispatch_packet` (will route through proxy after engine-proxy patch), parse FILE/REPLACE blocks, apply to worktree, `git -C wt commit -m "<step_id>"`. Resume from existing checkpoint.
- `src/harness/cli.py` — `coord_work` actually loads plan.json, locates WorkerTask by id, calls `run_worker`, writes result
- `tests/test_coord_worker.py` — extend with engine-call + worktree-edit tests (mock dispatcher)
- `tests/test_coord_coordinator.py` — extend with checkpoint-path + worktree-creation tests

## Required behavior changes

### coord/coordinator.py::launch_workers

```python
def launch_workers(self, plan, in_flight_limit=None):
    limit = in_flight_limit or self.max_workers
    # NEW: create worktree per worker before subprocess spawn
    from harness.coord.worktree import create_worktree
    launched = []
    for task in plan.tasks[:limit]:
        worktree = create_worktree(
            self.run_id, task.worker_id,
            base_branch="master",
            repo_root=self.project_root,
        )
        # subprocess.Popen([python, '-m', 'harness', 'coord', 'work',
        #                   '--run-id', self.run_id,
        #                   '--worker-id', task.worker_id])
        launched.append(task.worker_id)
    return {"launched": launched, "skipped": []}
```

### coord/coordinator.py::poll_workers — fix path

```python
ckpt_dir = self.run_dir / "checkpoints"   # was: self.run_dir
for ckpt_file in ckpt_dir.glob("worker-*.json"):
    ...
```

### coord/worker.py::run_worker — actually call engine

```python
for idx in range(start_idx, len(task_obj.steps)):
    step = task_obj.steps[idx]
    # Build prompt: read_set files + step.instruction
    prompt = _build_step_prompt(task_obj, step, wt_path)
    # Dispatch to engine (routes through proxy when v2 setup)
    result = dispatch_packet(
        project="harness-worker",
        packet_path=_write_temp_packet(prompt),
        force_engine=engine,
    )
    if result.success:
        # Parse FILE/REPLACE blocks, apply to wt_path
        applied = _apply_edits(result.text, wt_path)
        # Commit on worker branch
        subprocess.run(["git", "-C", str(wt_path), "add", "-A"], check=False)
        subprocess.run(
            ["git", "-C", str(wt_path), "commit", "-m", f"[{step.step_id}]"],
            check=False, capture_output=True,
        )
        commit_sha = subprocess.run(
            ["git", "-C", str(wt_path), "rev-parse", "HEAD"],
            check=False, capture_output=True, text=True,
        ).stdout.strip()
    # Update checkpoint with last_completed_step + files + commit
    ...
```

### cli.py::coord_work — wire to run_worker

```python
@coord_group.command(name="work")
@click.option("--run-id", required=True)
@click.option("--worker-id", required=True)
@click.option("--engine", default="swarm/kimi-api")
def coord_work(run_id, worker_id, engine):
    from harness.coord.worker import run_worker
    from harness.coord.schemas import WavePlan
    run_dir = Path(".harness") / "runs" / run_id
    plan = WavePlan.model_validate_json((run_dir / "plan.json").read_text())
    task = next((t for t in plan.tasks if t.worker_id == worker_id), None)
    if not task:
        click.echo(f"error: worker {worker_id} not in plan", err=True)
        sys.exit(1)
    result = run_worker(task.model_dump(), run_dir, engine=engine)
    click.echo(f"worker {worker_id}: {result['state']}")
    sys.exit(0 if result["state"] == "completed" else 1)
```

## Tests required

1. coord_work CLI invokes run_worker (mock it) and exits cleanly
2. coord_work returns non-zero when worker_id not in plan
3. run_worker actually invokes dispatch_packet for each step (mock dispatch)
4. run_worker applies FILE/REPLACE edits + commits per step
5. Coordinator.launch_workers calls create_worktree per task (mock)
6. Coordinator.poll_workers reads run_dir/checkpoints/*.json correctly

Target ≥6 new tests.

## Acceptance criteria

1. `harness coord work --run-id X --worker-id worker-1` actually runs (with mock plan + mock engine).
2. `pytest tests/test_coord_worker.py tests/test_coord_coordinator.py tests/test_coord_cli.py -q` green.
3. `pytest tests/ -q` full suite green.
4. Single commit: `feat(coord): wire CLI work + worker engine call + worktree creation + checkpoint path`.

## Reference

- spec/multi-agent-harness-architecture.md §3.1 (Coordinator) + §3.3 (Worker)
- Production audit findings #1, #2, #3, #8 (already documented above)
- src/harness/engines/dispatcher.py::dispatch_packet — call target

## Output format

3-4 file modifications + 2 test-file extensions + 1 commit.
