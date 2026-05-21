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
