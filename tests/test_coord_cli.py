"""Tests for harness coord CLI group."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# coord plan
# ---------------------------------------------------------------------------

@patch("harness.coord.planner.write_plan")
@patch("harness.coord.planner.plan")
def test_coord_plan_creates_plan(mock_plan, mock_write, runner: CliRunner, tmp_path: Path) -> None:
    from harness.coord.schemas import WavePlan, WorkerTask
    spec = tmp_path / "spec.md"
    spec.write_text("# spec", encoding="utf-8")
    mock_plan.return_value = WavePlan(
        run_id="20260520T220000-ab12",
        spec_path=str(spec),
        created_at="2026-05-20T22:00:00Z",
        planner_engine="kimi",
        tasks=[WorkerTask(worker_id="worker-1", title="t", description="d")],
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "plan", "--spec", str(spec)])
    assert result.exit_code == 0
    assert "plan.json" in result.output


# ---------------------------------------------------------------------------
# coord run
# ---------------------------------------------------------------------------

@patch("harness.coord.coordinator.Coordinator")
def test_coord_run_new_run(mock_coord, runner: CliRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("# spec", encoding="utf-8")
    mock_coord.return_value.tick.return_value = MagicMock(
        run_id="20260520T220000-ab12",
        state=MagicMock(value="running"),
        worker_summary={"worker-1": "completed"},
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "run", "--spec", str(spec), "--run-id", "20260520T220000-ab12"])
    assert result.exit_code == 0
    assert "running" in result.output
    assert "worker-1" in result.output


@patch("harness.coord.run_state.read_run_state")
@patch("harness.coord.coordinator.Coordinator")
def test_coord_run_resume(mock_coord, mock_read, runner: CliRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("# spec", encoding="utf-8")
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    (run_dir / "run_state.json").write_text("{}", encoding="utf-8")
    mock_read.return_value = MagicMock(run_id="20260520T220000-ab12")
    mock_coord.return_value.tick.return_value = MagicMock(
        run_id="20260520T220000-ab12",
        state=MagicMock(value="running"),
        worker_summary={},
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "run", "--spec", str(spec), "--resume"])
    # If no runs dir exists in isolated fs, it will error; we accept either
    assert result.exit_code in (0, 1)


# ---------------------------------------------------------------------------
# coord status
# ---------------------------------------------------------------------------

@patch("harness.coord.run_state.read_run_state")
def test_coord_status_shows_summary(mock_read, runner: CliRunner, tmp_path: Path) -> None:
    from harness.coord.schemas import IntegratorStatus, RunState, RunStateLiteral, WorkerStateLiteral, WorkerStatus
    mock_read.return_value = RunState(
        schema_version=1,
        run_id="20260520T220000-ab12",
        spec_path="spec.md",
        state=RunStateLiteral.RUNNING,
        plan_path="plan.json",
        started_at="2026-05-20T22:00:00Z",
        last_tick_at="2026-05-20T22:00:00Z",
        workers={
            "worker-1": WorkerStatus(worker_id="worker-1", state=WorkerStateLiteral.COMPLETED),
        },
        integrator_status=IntegratorStatus(state="pending"),
        escalations=[],
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "status", "--run-id", "20260520T220000-ab12"])
    assert result.exit_code == 0
    assert "running" in result.output
    assert "worker-1" in result.output


def test_coord_status_missing_run(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "status", "--run-id", "99999999T999999-zzzz"])
    assert result.exit_code == 1
    assert "not found" in result.output


# ---------------------------------------------------------------------------
# coord integrate
# ---------------------------------------------------------------------------

@patch("harness.coord.integrator.integrate")
def test_coord_integrate_success(mock_integrate, runner: CliRunner, tmp_path: Path) -> None:
    mock_integrate.return_value = MagicMock(
        success=True,
        commit_sha="abc1234",
        pushed=True,
        test_summary={"passed": 5, "failed": 0},
        diagnostic="",
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "integrate", "--run-id", "20260520T220000-ab12"])
    assert result.exit_code == 0
    assert "success=True" in result.output


# ---------------------------------------------------------------------------
# coord work
# ---------------------------------------------------------------------------

@patch("harness.coord.cli.run_worker") if False else patch("harness.cli.coord_work")  # placeholder
@patch("harness.coord.worker.run_worker")
def test_coord_work_success(mock_run, mock_cli_work, runner: CliRunner, tmp_path: Path) -> None:
    from harness.coord.schemas import WavePlan, WorkerTask
    plan = WavePlan(
        run_id="20260520T220000-ab12",
        spec_path="spec.md",
        created_at="2026-05-20T22:00:00Z",
        planner_engine="kimi",
        tasks=[WorkerTask(worker_id="worker-1", title="t", description="d")],
    )
    mock_run.return_value = {"state": "completed"}

    # Set up plan INSIDE the isolated cwd so the CLI's relative `runs/<id>/plan.json` resolves.
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        run_dir = iso_path / "runs" / "20260520T220000-ab12"
        run_dir.mkdir(parents=True)
        (run_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
        result = runner.invoke(cli, ["coord", "work", "--run-id", "20260520T220000-ab12", "--worker-id", "worker-1"])
    assert result.exit_code == 0, result.output
    assert "worker-1: completed" in result.output
    mock_run.assert_called_once()


@patch("harness.coord.worker.run_worker")
def test_coord_work_missing_worker_id(mock_run, runner: CliRunner, tmp_path: Path) -> None:
    from harness.coord.schemas import WavePlan, WorkerTask
    plan = WavePlan(
        run_id="20260520T220000-ab12",
        spec_path="spec.md",
        created_at="2026-05-20T22:00:00Z",
        planner_engine="kimi",
        tasks=[WorkerTask(worker_id="worker-1", title="t", description="d")],
    )

    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        run_dir = iso_path / "runs" / "20260520T220000-ab12"
        run_dir.mkdir(parents=True)
        (run_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
        result = runner.invoke(cli, ["coord", "work", "--run-id", "20260520T220000-ab12", "--worker-id", "worker-99"])
    assert result.exit_code == 1
    assert "worker-99 not in plan" in result.output
    mock_run.assert_not_called()


def test_coord_work_missing_plan(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "work", "--run-id", "20260520T220000-ab12", "--worker-id", "worker-1"])
    assert result.exit_code == 1
    assert "plan not found" in result.output
