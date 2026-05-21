# WORKER-RESUME-ON-RETRY — `harness coord retry <worker_id>`

## Goal

`src/harness/coord/worker.py::run_worker` already supports resuming from
the last checkpoint (the `resume_from` parameter), but there is no CLI
verb that invokes it.  Operators have to either manually edit the
checkpoint JSON or re-plan the whole run.  This wave adds a small retry
verb that re-dispatches a specific failed worker from its last step.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New CLI subcommand `harness coord retry <worker_id>`

Find `@coord_group.command(name="work")` in `src/harness/cli.py`
(around line 1330).  Add a NEW command AFTER `coord_work`:

```python
@coord_group.command(name="retry")
@click.option("--run-id", required=True)
@click.option("--worker-id", required=True)
@click.option("--engine", default="swarm/kimi-api",
              help="Engine to retry with; defaults to swarm/kimi-api.")
def coord_retry(run_id: str, worker_id: str, engine: str) -> None:
    """Re-dispatch a failed worker from its last checkpoint.

    Loads the existing checkpoint at runs/<run_id>/checkpoints/<worker_id>.json,
    resets state to 'in_progress', and calls run_worker with resume_from
    pointing at that checkpoint so the worker picks up where it left off.
    """
    from harness.coord.worker import run_worker
    from harness.coord.schemas import WavePlan
    from harness.coord.checkpoint import read_checkpoint, write_checkpoint

    run_dir = Path("runs") / run_id
    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        click.echo(f"error: plan not found for run {run_id}", err=True)
        sys.exit(1)
    plan = WavePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    task = next((t for t in plan.tasks if t.worker_id == worker_id), None)
    if task is None:
        click.echo(f"error: worker {worker_id} not in plan", err=True)
        sys.exit(1)

    ckpt_path = run_dir / "checkpoints" / f"{worker_id}.json"
    ckpt = read_checkpoint(ckpt_path)
    if ckpt is None:
        click.echo(f"error: no checkpoint at {ckpt_path}", err=True)
        sys.exit(1)
    if ckpt.state == "completed":
        click.echo(f"worker {worker_id} already completed; nothing to retry")
        sys.exit(0)

    # Reset state so the run loop treats it as in-progress
    reset = ckpt.model_copy(update={"state": "in_progress", "tests_passed": False})
    write_checkpoint(ckpt_path, reset)

    result = run_worker(task.model_dump(), run_dir, engine=engine, resume_from=ckpt_path)
    click.echo(f"worker {worker_id}: {result['state']}")
    sys.exit(0 if result["state"] == "completed" else 1)
```

### 2. Tests

`tests/test_coord_retry_cli.py`:

```python
"""Tests for `harness coord retry`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_plan_and_checkpoint(base: Path, run_id: str, worker_id: str,
                              ckpt_state: str = "failed") -> None:
    from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep
    from harness.coord.checkpoint import Checkpoint, write_checkpoint

    run_dir = base / "runs" / run_id
    (run_dir / "checkpoints").mkdir(parents=True)
    plan = WavePlan(
        run_id=run_id, spec_path="s.md", created_at="2026-05-21T00:00:00+00:00",
        planner_engine="mock",
        tasks=[WorkerTask(
            worker_id=worker_id, title="t", description="d",
            steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                              target_files=["x.txt"], expected_diff_lines=1)],
        )],
    )
    (run_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
    write_checkpoint(
        run_dir / "checkpoints" / f"{worker_id}.json",
        Checkpoint(worker_id=worker_id, run_id=run_id, state=ckpt_state),
    )


def test_retry_missing_plan(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "retry", "--run-id", "r1", "--worker-id", "worker-1"])
    assert result.exit_code == 1
    assert "plan not found" in result.output


def test_retry_unknown_worker(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_plan_and_checkpoint(iso_path, "20260521T000000-aabb", "worker-1")
        result = runner.invoke(cli, [
            "coord", "retry", "--run-id", "20260521T000000-aabb", "--worker-id", "worker-99",
        ])
    assert result.exit_code == 1
    assert "not in plan" in result.output


def test_retry_no_checkpoint(runner: CliRunner, tmp_path: Path) -> None:
    """Plan exists but checkpoint doesn't — exits 1 with clear error."""
    from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        run_dir = iso_path / "runs" / "20260521T000000-aabb"
        (run_dir / "checkpoints").mkdir(parents=True)
        plan = WavePlan(
            run_id="20260521T000000-aabb", spec_path="s.md",
            created_at="2026-05-21T00:00:00+00:00",
            planner_engine="mock",
            tasks=[WorkerTask(
                worker_id="worker-1", title="t", description="d",
                steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                                  target_files=["x.txt"], expected_diff_lines=1)],
            )],
        )
        (run_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
        result = runner.invoke(cli, [
            "coord", "retry", "--run-id", "20260521T000000-aabb", "--worker-id", "worker-1",
        ])
    assert result.exit_code == 1
    assert "no checkpoint" in result.output


def test_retry_completed_worker_short_circuits(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_plan_and_checkpoint(iso_path, "20260521T000000-aabb", "worker-1",
                                  ckpt_state="completed")
        result = runner.invoke(cli, [
            "coord", "retry", "--run-id", "20260521T000000-aabb", "--worker-id", "worker-1",
        ])
    assert result.exit_code == 0
    assert "already completed" in result.output


def test_retry_invokes_run_worker_with_resume_from(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_plan_and_checkpoint(iso_path, "20260521T000000-aabb", "worker-1",
                                  ckpt_state="failed")
        with patch("harness.coord.worker.run_worker") as mock_run:
            mock_run.return_value = {"state": "completed"}
            result = runner.invoke(cli, [
                "coord", "retry", "--run-id", "20260521T000000-aabb", "--worker-id", "worker-1",
            ])
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    # resume_from kwarg should be supplied
    kwargs = mock_run.call_args.kwargs
    assert "resume_from" in kwargs
```

## Acceptance

- `python -m pytest tests/test_coord_retry_cli.py` — green.
- Full suite stays green.
- `harness coord retry --help` shows the new verb.

## Constraints

- DO NOT modify `worker.py` — the resume_from path already exists.
- DO NOT touch the existing `coord work` command body.
- Use Click `isolated_filesystem(temp_dir=tmp_path)` in tests.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
