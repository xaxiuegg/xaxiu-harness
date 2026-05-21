"""Tests for `harness coord plan-from-description`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.planner import plan_from_description
from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep


def _stub_waveplan(run_id: str = "20260521T000000-aabb") -> WavePlan:
    return WavePlan(
        run_id=run_id, spec_path="x", created_at="2026-05-21T00:00:00+00:00",
        planner_engine="mock",
        tasks=[WorkerTask(
            worker_id="worker-1", title="t", description="d",
            steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                              target_files=["x.txt"], expected_diff_lines=1)],
        )],
    )


def test_plan_from_description_delegates_to_plan(monkeypatch) -> None:
    """plan_from_description writes description to temp file and calls plan()."""
    captured: dict = {}

    def fake_plan(path, **kwargs):
        captured["path"] = path
        captured["body"] = Path(path).read_text(encoding="utf-8")
        captured["kwargs"] = kwargs
        return _stub_waveplan()

    monkeypatch.setattr("harness.coord.planner.plan", fake_plan)
    waveplan = plan_from_description("Add /health endpoint", engine="mock")
    assert waveplan.run_id == "20260521T000000-aabb"
    assert "Add /health endpoint" in captured["body"]
    # Temp file was deleted after call
    assert not Path(captured["path"]).exists()


def test_cli_plan_from_description_writes_plan_json(monkeypatch, tmp_path: Path) -> None:
    """`harness coord plan-from-description` writes runs/<id>/plan.json."""
    runner = CliRunner()
    with patch("harness.coord.planner.plan_from_description") as mock_p, \
         patch("harness.coord.planner.write_plan") as mock_w:
        mock_p.return_value = _stub_waveplan()
        mock_w.return_value = tmp_path / "runs" / "20260521T000000-aabb" / "plan.json"
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, [
                "coord", "plan-from-description", "Add a /health endpoint",
                "--engine", "mock",
            ])
    assert result.exit_code == 0, result.output
    assert "plan.json written" in result.output
    assert "1 task(s)" in result.output


def test_cli_plan_from_description_propagates_run_id(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    with patch("harness.coord.planner.plan_from_description") as mock_p, \
         patch("harness.coord.planner.write_plan") as mock_w:
        mock_p.return_value = _stub_waveplan(run_id="20260521T010101-cccc")
        mock_w.return_value = tmp_path / "runs" / "20260521T010101-cccc" / "plan.json"
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, [
                "coord", "plan-from-description", "Test",
                "--engine", "mock", "--run-id", "20260521T010101-cccc",
            ])
    assert result.exit_code == 0, result.output
    # run_id forwarded to plan_from_description
    assert mock_p.call_args.kwargs.get("run_id") == "20260521T010101-cccc"
