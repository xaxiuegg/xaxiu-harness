"""Tests for `harness coord list`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_run(base: Path, run_id: str, state: str, tasks: int = 0,
              last_tick_at: str | None = None,
              started_at: str | None = None) -> None:
    run_dir = base / "runs" / run_id
    (run_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
    rs = {"state": state}
    if last_tick_at:
        rs["last_tick_at"] = last_tick_at
    if started_at:
        rs["started_at"] = started_at
    (run_dir / "run_state.json").write_text(json.dumps(rs), encoding="utf-8")
    (run_dir / "plan.json").write_text(
        json.dumps({"tasks": [{"worker_id": f"worker-{i}"} for i in range(tasks)]}),
        encoding="utf-8",
    )


def test_coord_list_no_runs(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "list"])
    assert result.exit_code == 0
    assert "no runs" in result.output


def test_coord_list_orders_by_last_tick_newest_first(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_run(iso_path, "r-old", state="completed",
                  last_tick_at="2026-05-21T01:00:00Z")
        _seed_run(iso_path, "r-new", state="running",
                  last_tick_at="2026-05-21T02:00:00Z")
        result = runner.invoke(cli, ["coord", "list"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "r-new" in out
    assert "r-old" in out
    # Newest first: r-new appears before r-old in output
    assert out.index("r-new") < out.index("r-old")


def test_coord_list_respects_limit(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        for i in range(5):
            _seed_run(iso_path, f"r{i}", state="completed",
                      last_tick_at=f"2026-05-21T0{i}:00:00Z")
        result = runner.invoke(cli, ["coord", "list", "--limit", "2"])
    assert result.exit_code == 0
    # Only 2 most-recent shown
    assert "r4" in result.output
    assert "r3" in result.output
    assert "r0" not in result.output


def test_coord_list_includes_task_count(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_run(iso_path, "r-tasks", state="running", tasks=3,
                  last_tick_at="2026-05-21T01:00:00Z")
        result = runner.invoke(cli, ["coord", "list"])
    assert result.exit_code == 0
    # Should show "3" in the TASKS column for r-tasks
    assert "r-tasks" in result.output
    line = next(ln for ln in result.output.splitlines() if "r-tasks" in ln)
    assert "3" in line
