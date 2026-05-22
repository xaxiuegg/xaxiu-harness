"""Tests for harness.coord.integrator."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.coord.integrator import IntegrationReport, integrate
from harness.coord.run_state import write_run_state
from harness.coord.schemas import IntegratorStatus, RunState, RunStateLiteral


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_state(run_dir: Path, run_id: str = "20260520T220000-ab12") -> None:
    state = RunState(
        schema_version=1,
        run_id=run_id,
        spec_path="spec.md",
        state=RunStateLiteral.INTEGRATING,
        plan_path=str(run_dir / "plan.json"),
        started_at="2026-05-20T22:00:00Z",
        last_tick_at="2026-05-20T22:00:00Z",
        workers={},
        integrator_status=IntegratorStatus(state="pending"),
        escalations=[],
    )
    write_run_state(run_dir / "run_state.json", state)


# ---------------------------------------------------------------------------
# integrate
# ---------------------------------------------------------------------------

def test_integrate_missing_run_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    report = integrate(run_dir)
    assert report.success is False
    assert "No run_state" in report.diagnostic


@patch("harness.coord.integrator.subprocess.run")
def test_integrate_dry_run_success(mock_run, tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    _make_run_state(run_dir)
    mock_run.return_value = MagicMock(
        stdout="5 passed, 1 failed, 2 skipped in 1.23s",
        returncode=0,
    )
    report = integrate(run_dir)
    # dry_run: success depends on test results
    assert report.test_summary is not None
    assert report.test_summary["passed"] == 5


@patch("harness.coord.integrator.subprocess.run")
def test_integrate_env_gate_blocks_commit(mock_run, tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    _make_run_state(run_dir)
    monkeypatch.delenv("HARNESS_ALLOW_AUTO_INTEGRATE", raising=False)
    mock_run.return_value = MagicMock(
        stdout="5 passed in 1.23s",
        returncode=0,
    )
    report = integrate(run_dir, auto_commit=True)
    # Gate not set → dry run
    assert report.pushed is False
    assert report.commit_sha is None


@patch("harness.coord.integrator.subprocess.run")
def test_integrate_auto_commit_and_push(mock_run, tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    _make_run_state(run_dir)
    monkeypatch.setenv("HARNESS_ALLOW_AUTO_INTEGRATE", "true")

    def side_effect(cmd, **kwargs):
        if "commit" in cmd:
            return MagicMock(returncode=0, stdout="abc1234\n")
        if "push" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="5 passed in 1.23s")

    mock_run.side_effect = side_effect
    report = integrate(run_dir, auto_commit=True, auto_push=True)
    assert report.success is True
    assert report.commit_sha == "abc1234"
    assert report.pushed is True


@patch("harness.coord.integrator.subprocess.run")
def test_integrate_pytest_failure(mock_run, tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    _make_run_state(run_dir)
    mock_run.return_value = MagicMock(
        stdout="3 passed, 2 failed in 1.23s",
        returncode=1,
    )
    report = integrate(run_dir)
    assert report.test_summary is not None
    assert report.test_summary["failed"] == 2
    assert report.success is False


# ---------------------------------------------------------------------------
# integrate — worker-branch merge (INTEGRATOR-GIT-MERGE)
# ---------------------------------------------------------------------------

import subprocess


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


def test_integrate_merges_completed_worker_branches(tmp_path: Path, monkeypatch) -> None:
    """Real git: completed worker's branch is merged into master via squash strategy."""
    from harness.coord.checkpoint import Checkpoint, write_checkpoint
    from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "master"], repo)
    _git(["config", "user.email", "i@test.local"], repo)
    _git(["config", "user.name", "I"], repo)
    (repo / "README.md").write_text("# base\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-m", "base"], repo)

    # Create worker branch with one new file
    run_id = "20260521T010101-aabb"
    branch = f"wt/{run_id}/worker-1"
    _git(["checkout", "-b", branch], repo)
    (repo / "worker-out.txt").write_text("hello from worker-1\n", encoding="utf-8")
    _git(["add", "worker-out.txt"], repo)
    _git(["commit", "-m", "[s1] worker-1"], repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git(["checkout", "master"], repo)

    # Write plan + checkpoint + run_state
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True)
    plan = WavePlan(
        run_id=run_id,
        spec_path="spec.md",
        created_at="2026-05-21T01:01:01+00:00",
        planner_engine="mock",
        tasks=[WorkerTask(
            worker_id="worker-1", title="t", description="d",
            steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                              target_files=["worker-out.txt"], expected_diff_lines=1)],
        )],
        integration_strategy="squash",
    )
    (run_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
    (run_dir / "checkpoints").mkdir()
    write_checkpoint(
        run_dir / "checkpoints" / "worker-1.json",
        Checkpoint(worker_id="worker-1", run_id=run_id, state="completed", commit_sha=sha),
    )
    _make_run_state(run_dir, run_id=run_id)

    # Stub pytest only — let real subprocess.run handle the git commands.
    real_run = subprocess.run

    def smart(cmd, **kwargs):
        if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "python" and cmd[1] == "-m":
            return MagicMock(stdout="1 passed in 0.01s", returncode=0)
        return real_run(cmd, **kwargs)

    with patch("harness.coord.integrator.subprocess.run", side_effect=smart):
        report = integrate(run_dir, project_root=repo)

    assert report.workers_merged == ["worker-1"], (
        f"merged={report.workers_merged} skipped={report.workers_skipped} "
        f"conflicted={report.workers_conflicted} diag={report.diagnostic!r}"
    )
    assert report.workers_conflicted == []
    # File should now be staged on master (squash strategy stages but does not commit)
    rc = real_run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True,
    )
    assert "worker-out.txt" in rc.stdout


def test_integrate_skips_uncompleted_workers(tmp_path: Path) -> None:
    """Workers without a completed checkpoint are silently skipped."""
    from harness.coord.checkpoint import Checkpoint, write_checkpoint
    from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "master"], repo)
    _git(["config", "user.email", "i@test.local"], repo)
    _git(["config", "user.name", "I"], repo)
    (repo / "README.md").write_text("# base\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-m", "base"], repo)

    run_id = "20260521T020202-ccdd"
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True)
    plan = WavePlan(
        run_id=run_id,
        spec_path="spec.md",
        created_at="2026-05-21T02:02:02+00:00",
        planner_engine="mock",
        tasks=[WorkerTask(
            worker_id="worker-1", title="t", description="d",
            steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                              target_files=["x.txt"], expected_diff_lines=1)],
        )],
    )
    (run_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
    (run_dir / "checkpoints").mkdir()
    write_checkpoint(
        run_dir / "checkpoints" / "worker-1.json",
        Checkpoint(worker_id="worker-1", run_id=run_id, state="in_progress"),
    )
    _make_run_state(run_dir, run_id=run_id)

    real_run = subprocess.run

    def smart(cmd, **kwargs):
        if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "python" and cmd[1] == "-m":
            return MagicMock(stdout="1 passed in 0.01s", returncode=0)
        return real_run(cmd, **kwargs)

    with patch("harness.coord.integrator.subprocess.run", side_effect=smart):
        report = integrate(run_dir, project_root=repo)

    assert report.workers_merged == []
    assert report.workers_skipped == ["worker-1"]
    assert report.workers_conflicted == []


# ---------------------------------------------------------------------------
# WIRE-INTEGRATOR-TIMEOUT (2026-05-22) — D8
# ---------------------------------------------------------------------------

def test_resolve_pytest_timeout_uses_explicit_arg() -> None:
    from harness.coord.integrator import _resolve_pytest_timeout
    assert _resolve_pytest_timeout(900) == 900


def test_resolve_pytest_timeout_uses_env_when_no_explicit(monkeypatch) -> None:
    from harness.coord.integrator import _resolve_pytest_timeout
    monkeypatch.setenv("HARNESS_INTEGRATOR_PYTEST_TIMEOUT", "1200")
    assert _resolve_pytest_timeout(None) == 1200


def test_resolve_pytest_timeout_falls_back_to_default(monkeypatch) -> None:
    from harness.coord.integrator import _resolve_pytest_timeout, DEFAULT_PYTEST_TIMEOUT_SEC
    monkeypatch.delenv("HARNESS_INTEGRATOR_PYTEST_TIMEOUT", raising=False)
    assert _resolve_pytest_timeout(None) == DEFAULT_PYTEST_TIMEOUT_SEC
    assert DEFAULT_PYTEST_TIMEOUT_SEC >= 600  # the post-battle-test floor


def test_resolve_pytest_timeout_ignores_invalid_env(monkeypatch) -> None:
    from harness.coord.integrator import _resolve_pytest_timeout, DEFAULT_PYTEST_TIMEOUT_SEC
    monkeypatch.setenv("HARNESS_INTEGRATOR_PYTEST_TIMEOUT", "not-a-number")
    assert _resolve_pytest_timeout(None) == DEFAULT_PYTEST_TIMEOUT_SEC


def test_resolve_pytest_timeout_ignores_zero_and_negative(monkeypatch) -> None:
    from harness.coord.integrator import _resolve_pytest_timeout, DEFAULT_PYTEST_TIMEOUT_SEC
    monkeypatch.delenv("HARNESS_INTEGRATOR_PYTEST_TIMEOUT", raising=False)
    assert _resolve_pytest_timeout(0) == DEFAULT_PYTEST_TIMEOUT_SEC
    assert _resolve_pytest_timeout(-1) == DEFAULT_PYTEST_TIMEOUT_SEC


@patch("harness.coord.integrator.subprocess.run")
def test_integrate_passes_timeout_to_subprocess_run(mock_run, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_INTEGRATOR_PYTEST_TIMEOUT", raising=False)
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    _make_run_state(run_dir)
    mock_run.return_value = MagicMock(stdout="1 passed in 0.01s", returncode=0)
    integrate(run_dir, pytest_timeout=750)
    # Find the pytest invocation and assert its timeout
    pytest_calls = [c for c in mock_run.call_args_list
                    if c.args and isinstance(c.args[0], list)
                    and "pytest" in c.args[0]]
    assert pytest_calls, "no pytest subprocess call observed"
    assert pytest_calls[0].kwargs.get("timeout") == 750
