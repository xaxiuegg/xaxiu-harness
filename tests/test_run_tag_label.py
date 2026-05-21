"""Tests for RUN-TAG-LABEL + COORD-RUN-DRY-RUN."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.schemas import RunState, RunStateLiteral, IntegratorStatus
from harness.dashboard.v2_routes import list_runs


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make_run_state(run_id: str, label: str | None = None) -> RunState:
    return RunState(
        schema_version=1, run_id=run_id, spec_path="s.md",
        state=RunStateLiteral.RUNNING, plan_path="",
        started_at="2026-05-21T01:00:00Z", last_tick_at="2026-05-21T01:00:00Z",
        workers={}, integrator_status=IntegratorStatus(state="pending"),
        escalations=[], label=label,
    )


def _seed_run(base: Path, run_id: str, label: str | None = None) -> Path:
    run_dir = base / "runs" / run_id
    run_dir.mkdir(parents=True)
    rs = _make_run_state(run_id, label).model_dump(mode="json")
    (run_dir / "run_state.json").write_text(json.dumps(rs), encoding="utf-8")
    (run_dir / "plan.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
    return run_dir


def test_runstate_schema_accepts_label() -> None:
    rs = _make_run_state("20260521T010101-aabb", label="v0.5-smoke")
    assert rs.label == "v0.5-smoke"


def test_list_runs_includes_label(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_run(tmp_path, "20260521T010101-aabb", label="release")
    runs = list_runs()
    assert any(r.get("label") == "release" for r in runs)


def test_list_runs_filter_by_label(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_run(tmp_path, "20260521T010101-aabb", label="release")
    _seed_run(tmp_path, "20260521T020202-bbcc", label="dev")
    _seed_run(tmp_path, "20260521T030303-ccdd", label=None)

    only_release = list_runs(label="release")
    assert len(only_release) == 1
    assert only_release[0]["run_id"] == "20260521T010101-aabb"

    only_dev = list_runs(label="dev")
    assert len(only_dev) == 1


def test_cli_coord_list_shows_label_column(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_run(iso_path, "20260521T010101-aabb", label="release-v0.5")
        result = runner.invoke(cli, ["coord", "list"])
    assert result.exit_code == 0, result.output
    assert "LABEL" in result.output
    assert "release-v0.5" in result.output


def test_cli_coord_list_filters_by_label(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_run(iso_path, "20260521T010101-aabb", label="release")
        _seed_run(iso_path, "20260521T020202-bbcc", label="dev")
        result = runner.invoke(cli, ["coord", "list", "--label", "dev"])
    assert result.exit_code == 0
    assert "20260521T020202-bbcc" in result.output
    assert "20260521T010101-aabb" not in result.output


def test_cli_coord_run_dry_run_prints_plan_without_dispatching(runner: CliRunner, tmp_path: Path) -> None:
    """--dry-run prints the would-be plan + worker assignments and exits 0."""
    from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep
    stub_plan = WavePlan(
        run_id="20260521T010101-aabb", spec_path="s.md",
        created_at="2026-05-21T00:00:00+00:00", planner_engine="mock",
        tasks=[WorkerTask(
            worker_id="worker-1", title="Add /health", description="d",
            write_set=["health.py"],
            steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                              target_files=["health.py"], expected_diff_lines=1)],
        )],
    )
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        spec = iso_path / "spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        with patch("harness.coord.planner.plan", return_value=stub_plan), \
             patch("harness.coord.coordinator.Coordinator") as mock_coord:
            result = runner.invoke(cli, [
                "coord", "run", "--spec", str(spec),
                "--run-id", "20260521T010101-aabb",
                "--label", "test-label",
                "--dry-run",
            ])
    assert result.exit_code == 0, result.output
    assert "dry-run: would create run 20260521T010101-aabb" in result.output
    assert "label: test-label" in result.output
    assert "Add /health" in result.output
    assert "health.py" in result.output
    # Coordinator must NOT have been instantiated in dry-run mode
    mock_coord.assert_not_called()


def test_cli_coord_run_dry_run_planner_failure_exits_1(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        spec = iso_path / "spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        with patch("harness.coord.planner.plan", side_effect=RuntimeError("boom")):
            result = runner.invoke(cli, [
                "coord", "run", "--spec", str(spec),
                "--dry-run",
            ])
    assert result.exit_code == 1
    assert "planner failed" in result.output
