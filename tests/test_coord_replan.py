"""Tests for COORD-REPLAN-ON-FAIL — planner.replan_from_run + `harness coord replan`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.planner import replan_from_run
from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep


def _make_waveplan(run_id: str, spec_path: str) -> WavePlan:
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


def _seed_failed_run(base: Path, run_id: str, spec_text: str,
                     failed_workers: list[str]) -> Path:
    """Create a runs/<id> dir with plan.json + failed checkpoints + spec file."""
    run_dir = base / "runs" / run_id
    (run_dir / "checkpoints").mkdir(parents=True)
    spec_file = base / "spec.md"
    spec_file.write_text(spec_text, encoding="utf-8")

    plan_obj = _make_waveplan(run_id=run_id, spec_path=str(spec_file))
    (run_dir / "plan.json").write_text(plan_obj.model_dump_json(), encoding="utf-8")

    for wid in failed_workers:
        (run_dir / "checkpoints" / f"{wid}.json").write_text(json.dumps({
            "worker_id": wid,
            "run_id": run_id,
            "state": "failed",
            "tests_summary": "0p/2f/0s",
            "diagnostic": "L3.worker.E_TEST_FAILED",
            "files_modified": [],
        }), encoding="utf-8")
    return run_dir


def test_replan_from_run_missing_plan_raises(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "nope"
    run_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        replan_from_run(run_dir, engine="mock")


def test_replan_from_run_appends_failure_feedback(tmp_path: Path, monkeypatch) -> None:
    """The augmented spec passed to plan() includes the failed workers' diagnostics."""
    run_dir = _seed_failed_run(tmp_path, "20260521T000000-aabb",
                               "# Original spec\n\nDo a thing.\n",
                               failed_workers=["worker-1"])

    captured: dict = {}

    def fake_plan(path, **kwargs):
        captured["body"] = Path(path).read_text(encoding="utf-8")
        return _make_waveplan("20260521T010000-cccc", spec_path=str(path))

    monkeypatch.setattr("harness.coord.planner.plan", fake_plan)
    waveplan = replan_from_run(run_dir, engine="mock")
    assert waveplan.run_id == "20260521T010000-cccc"
    assert "Replan feedback" in captured["body"]
    assert "worker-1" in captured["body"]
    assert "0p/2f/0s" in captured["body"]


def test_replan_from_run_no_failures_still_replans(tmp_path: Path, monkeypatch) -> None:
    """When checkpoints exist but none are failed, replan still happens but feedback is empty."""
    run_dir = _seed_failed_run(tmp_path, "20260521T000000-aabb",
                               "# spec\n", failed_workers=[])

    captured: dict = {}

    def fake_plan(path, **kwargs):
        captured["body"] = Path(path).read_text(encoding="utf-8")
        return _make_waveplan("20260521T020000-dddd", spec_path=str(path))

    monkeypatch.setattr("harness.coord.planner.plan", fake_plan)
    waveplan = replan_from_run(run_dir, engine="mock")
    assert "Replan feedback" not in captured["body"]
    assert waveplan.run_id == "20260521T020000-dddd"


def test_cli_coord_replan_unknown_run(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "replan", "--run-id", "nope"])
    assert result.exit_code == 1
    assert "no such run" in result.output


def test_cli_coord_replan_happy_path(tmp_path: Path) -> None:
    """`harness coord replan` writes a new plan.json at runs/<new_id>/plan.json."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        run_dir = _seed_failed_run(iso_path, "20260521T000000-aabb",
                                   "# spec\n", failed_workers=["worker-1"])
        with patch("harness.coord.planner.replan_from_run") as mock_re, \
             patch("harness.coord.planner.write_plan") as mock_w:
            mock_re.return_value = _make_waveplan(
                run_id="20260521T030000-eeee",
                spec_path=str(iso_path / "spec.md"),
            )
            mock_w.return_value = iso_path / "runs" / "20260521T030000-eeee" / "plan.json"
            result = runner.invoke(cli, [
                "coord", "replan",
                "--run-id", "20260521T000000-aabb",
                "--engine", "mock",
            ])
    assert result.exit_code == 0, result.output
    assert "20260521T030000-eeee" in result.output
    assert "1 task(s)" in result.output
