"""Tests for harness.coord.coordinator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.coord.coordinator import CoordinationReport, Coordinator
from harness.coord.schemas import (
    IntegratorStatus,
    RunState,
    RunStateLiteral,
    WavePlan,
    WorkerStateLiteral,
    WorkerStatus,
    WorkerTask,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_plan(run_id: str = "20260520T220000-ab12") -> WavePlan:
    return WavePlan(
        run_id=run_id,
        spec_path="spec.md",
        created_at="2026-05-20T22:00:00Z",
        planner_engine="kimi",
        tasks=[
            WorkerTask(
                worker_id="worker-1",
                title="Fix bug",
                description="Fix it",
                steps=[],
            ),
            WorkerTask(
                worker_id="worker-2",
                title="Add test",
                description="Add it",
                steps=[],
                depends_on=["worker-1"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# init / paths
# ---------------------------------------------------------------------------

def test_coordinator_init_creates_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    assert not run_dir.exists()
    Coordinator(run_id="r1", run_dir=run_dir)
    assert run_dir.exists()


def test_coordinator_state_path_and_plan_path(tmp_path: Path) -> None:
    c = Coordinator(run_id="r1", run_dir=tmp_path)
    assert c.state_path == tmp_path / "run_state.json"
    assert c.plan_path == tmp_path / "plan.json"


# ---------------------------------------------------------------------------
# ensure_plan
# ---------------------------------------------------------------------------

def test_ensure_plan_loads_existing_plan(tmp_path: Path) -> None:
    plan = _valid_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")

    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    with patch("harness.coord.coordinator.run_planner") as mock_plan:
        result = c.ensure_plan(Path("spec.md"))
    mock_plan.assert_not_called()
    assert result.run_id == plan.run_id


@patch("harness.coord.coordinator.run_planner")
@patch("harness.coord.coordinator.write_plan")
def test_ensure_plan_invokes_planner_when_missing(mock_write, mock_plan, tmp_path: Path) -> None:
    mock_plan.return_value = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    result = c.ensure_plan(Path("spec.md"), engine="deepseek")
    mock_plan.assert_called_once()
    assert result.run_id == "20260520T220000-ab12"


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------

def test_tick_planning_to_running(tmp_path: Path) -> None:
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    with patch("harness.coord.coordinator.run_planner") as mock_plan:
        mock_plan.return_value = _valid_plan()
        report = c.tick(Path("spec.md"))
    assert report.state == RunStateLiteral.RUNNING
    assert c.state_path.exists()


def test_tick_running_launches_workers(tmp_path: Path) -> None:
    plan = _valid_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")

    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    # Pre-seed state as RUNNING
    from harness.coord.run_state import write_run_state
    state = RunState(
        schema_version=1,
        run_id=c.run_id,
        spec_path="spec.md",
        state=RunStateLiteral.RUNNING,
        plan_path=str(plan_path),
        started_at="2026-05-20T22:00:00Z",
        last_tick_at="2026-05-20T22:00:00Z",
        workers={},
        integrator_status=IntegratorStatus(state="pending"),
        escalations=[],
    )
    write_run_state(c.state_path, state)

    with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=1234, poll=MagicMock(return_value=None))
        report = c.tick(Path("spec.md"), in_flight_limit=2)
    assert report.state == RunStateLiteral.RUNNING
    mock_popen.assert_called()


def test_tick_running_to_integrating_when_all_done(tmp_path: Path) -> None:
    plan = _valid_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")

    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    from harness.coord.run_state import write_run_state
    from harness.coord.checkpoint import write_checkpoint, Checkpoint
    state = RunState(
        schema_version=1,
        run_id=c.run_id,
        spec_path="spec.md",
        state=RunStateLiteral.RUNNING,
        plan_path=str(plan_path),
        started_at="2026-05-20T22:00:00Z",
        last_tick_at="2026-05-20T22:00:00Z",
        workers={},
        integrator_status=IntegratorStatus(state="pending"),
        escalations=[],
    )
    write_run_state(c.state_path, state)

    # Write completed checkpoints for both workers
    checkpoints_dir = tmp_path / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    for wid in ("worker-1", "worker-2"):
        write_checkpoint(
            checkpoints_dir / f"{wid}.json",
            Checkpoint(worker_id=wid, run_id=c.run_id, state="completed"),
        )

    report = c.tick(Path("spec.md"))
    assert report.state == RunStateLiteral.INTEGRATING


# ---------------------------------------------------------------------------
# launch_workers
# ---------------------------------------------------------------------------

def test_launch_workers_respects_in_flight_limit(tmp_path: Path) -> None:
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)

    with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=1234, poll=MagicMock(return_value=None))
        result = c.launch_workers(plan, in_flight_limit=1)
    # Only worker-1 should launch (worker-2 is blocked by deps)
    assert len(result["launched"]) <= 1
    assert "worker-1" in result["launched"] or "worker-1" in result["skipped"]


def test_launch_workers_creates_worktree_before_spawn(tmp_path: Path) -> None:
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)

    with patch("harness.coord.coordinator.create_worktree") as mock_wt:
        with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=1234, poll=MagicMock(return_value=None))
            c.launch_workers(plan)

    mock_wt.assert_called_once_with(
        "20260520T220000-ab12", "worker-1", base_branch="master", repo_root=c.project_root
    )
    mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# poll_workers
# ---------------------------------------------------------------------------

def test_poll_workers_reads_checkpoints(tmp_path: Path) -> None:
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    from harness.coord.checkpoint import write_checkpoint, Checkpoint
    checkpoints_dir = tmp_path / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    write_checkpoint(
        checkpoints_dir / "worker-1.json",
        Checkpoint(worker_id="worker-1", run_id=c.run_id, state="in_progress", updated_at="2026-05-20T22:00:00Z"),
    )
    statuses = c.poll_workers()
    assert "worker-1" in statuses
    assert statuses["worker-1"].state == WorkerStateLiteral.IN_PROGRESS
