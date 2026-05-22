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

    # Worker-1 has no deps → branches from master.
    mock_wt.assert_called_once_with(
        "20260520T220000-ab12", "worker-1", base_branch="master", repo_root=c.project_root
    )
    mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# WIRE-DEP-BRANCH (2026-05-22) — D5
# ---------------------------------------------------------------------------

def test_launch_workers_branches_from_parent_when_dep_branch_exists(tmp_path: Path) -> None:
    """If worker-2 depends on worker-1 and wt/<rid>/worker-1 exists, worker-2 branches from there."""
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)

    # Pretend worker-1 has already completed (checkpoint state=completed)
    from harness.coord.checkpoint import write_checkpoint, Checkpoint
    ckpts = tmp_path / "checkpoints"
    ckpts.mkdir(parents=True, exist_ok=True)
    write_checkpoint(
        ckpts / "worker-1.json",
        Checkpoint(worker_id="worker-1", run_id=c.run_id, state="completed",
                   commit_sha="abc1234", updated_at="2026-05-22T01:00:00Z"),
    )

    # _git_branch_exists is patched to claim parent branch exists
    with patch("harness.coord.coordinator._git_branch_exists", return_value=True):
        with patch("harness.coord.coordinator.create_worktree") as mock_wt:
            with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock(pid=1, poll=MagicMock(return_value=None))
                c.launch_workers(plan)

    # worker-2 should be launched (worker-1 deps met) and branched from worker-1
    worker2_calls = [call for call in mock_wt.call_args_list
                     if call.args[1] == "worker-2"]
    assert len(worker2_calls) == 1
    assert worker2_calls[0].kwargs["base_branch"] == "wt/20260520T220000-ab12/worker-1"


def test_launch_workers_falls_back_to_master_when_parent_branch_missing(tmp_path: Path) -> None:
    """If parent branch hasn't been created yet, worker still launches from master (recover-friendly)."""
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)

    from harness.coord.checkpoint import write_checkpoint, Checkpoint
    ckpts = tmp_path / "checkpoints"
    ckpts.mkdir(parents=True, exist_ok=True)
    write_checkpoint(
        ckpts / "worker-1.json",
        Checkpoint(worker_id="worker-1", run_id=c.run_id, state="completed",
                   commit_sha="abc1234", updated_at="2026-05-22T01:00:00Z"),
    )

    with patch("harness.coord.coordinator._git_branch_exists", return_value=False):
        with patch("harness.coord.coordinator.create_worktree") as mock_wt:
            with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock(pid=1, poll=MagicMock(return_value=None))
                c.launch_workers(plan)

    worker2_calls = [call for call in mock_wt.call_args_list
                     if call.args[1] == "worker-2"]
    assert len(worker2_calls) == 1
    assert worker2_calls[0].kwargs["base_branch"] == "master"


def test_git_branch_exists_returns_false_for_unknown_branch(tmp_path: Path) -> None:
    from harness.coord.coordinator import _git_branch_exists
    # tmp_path is not a git repo, so the call exit-code is non-zero → False
    assert _git_branch_exists("nonexistent-branch", tmp_path) is False


# ---------------------------------------------------------------------------
# launch_workers — detachment + per-worker log (WIRE-WORKER-DETACH 2026-05-22)
# ---------------------------------------------------------------------------

def test_launch_workers_creates_per_worker_log_file(tmp_path: Path) -> None:
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    with patch("harness.coord.coordinator.create_worktree"):
        with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=1, poll=MagicMock(return_value=None))
            c.launch_workers(plan)
    log_path = tmp_path / "workers" / "worker-1.log"
    assert log_path.exists(), "per-worker log file should be created"


def test_launch_workers_uses_python_m_harness_not_harness_cli(tmp_path: Path) -> None:
    """WIRE-MAIN-ENTRY (2026-05-22): the Popen cmd must invoke `python -m harness`,
    not `python -m harness.cli`.  The latter loads the module but never runs
    main(), so the worker subprocess exits 0 instantly — the real reason
    Round-1 battle-test workers produced no checkpoints."""
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    with patch("harness.coord.coordinator.create_worktree"):
        with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=1, poll=MagicMock(return_value=None))
            c.launch_workers(plan)
    args, _ = mock_popen.call_args
    cmd = args[0]
    # cmd is [sys.executable, "-m", "harness", "coord", "work", ...]
    assert cmd[1] == "-m"
    assert cmd[2] == "harness", (
        f"expected `python -m harness ...`, got `python -m {cmd[2]} ...` — "
        "this is the WIRE-MAIN-ENTRY regression sentinel"
    )


def test_launch_workers_redirects_stdout_to_log_not_devnull(tmp_path: Path) -> None:
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    import subprocess as _sp
    with patch("harness.coord.coordinator.create_worktree"):
        with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=1, poll=MagicMock(return_value=None))
            c.launch_workers(plan)
    _, kwargs = mock_popen.call_args
    # stdout must NOT be DEVNULL — the battle-test defect was exactly that.
    assert kwargs["stdout"] is not _sp.DEVNULL
    # stderr should be folded into stdout so the single log file captures both
    assert kwargs["stderr"] == _sp.STDOUT
    # stdin DEVNULL so the detached child can't block on input
    assert kwargs["stdin"] == _sp.DEVNULL


def test_launch_workers_detaches_on_windows(tmp_path: Path) -> None:
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    with patch("harness.coord.coordinator.create_worktree"):
        with patch("harness.coord.coordinator.os") as mock_os:
            mock_os.name = "nt"
            mock_os.path = __import__("os").path  # let Path operations still work
            with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock(pid=1, poll=MagicMock(return_value=None))
                c.launch_workers(plan)
    _, kwargs = mock_popen.call_args
    # 0x00000008 DETACHED_PROCESS | 0x00000200 CREATE_NEW_PROCESS_GROUP
    assert kwargs.get("creationflags") == (0x00000008 | 0x00000200)


def test_launch_workers_uses_start_new_session_on_posix(tmp_path: Path) -> None:
    plan = _valid_plan()
    c = Coordinator(run_id="20260520T220000-ab12", run_dir=tmp_path)
    with patch("harness.coord.coordinator.create_worktree"):
        with patch("harness.coord.coordinator.os") as mock_os:
            mock_os.name = "posix"
            mock_os.path = __import__("os").path
            with patch("harness.coord.coordinator.subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock(pid=1, poll=MagicMock(return_value=None))
                c.launch_workers(plan)
    _, kwargs = mock_popen.call_args
    assert kwargs.get("start_new_session") is True
    assert "creationflags" not in kwargs


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
