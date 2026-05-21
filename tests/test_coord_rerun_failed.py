"""Tests for COORD-RERUN-FAILED."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep


def _make_wp(run_id: str, spec_path: str) -> WavePlan:
    return WavePlan(
        run_id=run_id, spec_path=spec_path,
        created_at="2026-05-21T00:00:00+00:00",
        planner_engine="mock",
        tasks=[WorkerTask(
            worker_id="worker-1", title="t", description="d",
            steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                              target_files=["x.txt"], expected_diff_lines=1)],
        )],
    )


def test_rerun_failed_unknown_run(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "rerun-failed", "--run-id", "nope"])
    assert result.exit_code == 1
    assert "no such run" in result.output


def test_rerun_failed_chains_replan_and_run(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        old_run_dir = iso_path / "runs" / "20260521T000000-aabb"
        old_run_dir.mkdir(parents=True)
        spec = iso_path / "spec.md"
        spec.write_text("# spec\n", encoding="utf-8")

        with patch("harness.coord.planner.replan_from_run") as mock_re, \
             patch("harness.coord.planner.write_plan") as mock_w, \
             patch("harness.coord.coordinator.Coordinator") as mock_coord:
            mock_re.return_value = _make_wp("20260521T010000-cccc", str(spec))
            mock_w.return_value = iso_path / "runs" / "20260521T010000-cccc" / "plan.json"
            mock_coord.return_value.tick.return_value = MagicMock(
                run_id="20260521T010000-cccc",
                state=MagicMock(value="running"),
                worker_summary={"worker-1": "completed"},
            )
            result = runner.invoke(cli, [
                "coord", "rerun-failed",
                "--run-id", "20260521T000000-aabb",
                "--engine", "mock",
            ])

    assert result.exit_code == 0, result.output
    assert "20260521T010000-cccc" in result.output
    assert "worker-1: completed" in result.output


def test_rerun_failed_auto_integrate(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        (iso_path / "runs" / "20260521T000000-aabb").mkdir(parents=True)
        spec = iso_path / "spec.md"
        spec.write_text("# spec\n", encoding="utf-8")

        with patch("harness.coord.planner.replan_from_run") as mock_re, \
             patch("harness.coord.planner.write_plan") as mock_w, \
             patch("harness.coord.coordinator.Coordinator") as mock_coord, \
             patch("harness.coord.integrator.integrate") as mock_int:
            mock_re.return_value = _make_wp("20260521T010000-cccc", str(spec))
            mock_w.return_value = iso_path / "runs" / "20260521T010000-cccc" / "plan.json"
            mock_coord.return_value.tick.return_value = MagicMock(
                run_id="20260521T010000-cccc",
                state=MagicMock(value="completed"),
                worker_summary={},
            )
            mock_int.return_value = MagicMock(
                success=True, workers_merged=["worker-1"], workers_conflicted=[],
            )
            result = runner.invoke(cli, [
                "coord", "rerun-failed",
                "--run-id", "20260521T000000-aabb",
                "--auto-integrate",
            ])

    assert result.exit_code == 0, result.output
    assert "integrate: success=True" in result.output
