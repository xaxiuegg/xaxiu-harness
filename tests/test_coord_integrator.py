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
