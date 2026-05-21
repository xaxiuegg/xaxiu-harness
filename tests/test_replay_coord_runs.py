"""Tests for REPLAY-COORD-RUNS — replay_coord_run + CLI routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.replay import replay_coord_run, format_coord_for_human


def _seed_run(base: Path, run_id: str) -> Path:
    run_dir = base / "runs" / run_id
    (run_dir / "checkpoints").mkdir(parents=True)
    (run_dir / "run_state.json").write_text(json.dumps({
        "state": "completed", "run_id": run_id,
    }), encoding="utf-8")
    (run_dir / "plan.json").write_text(json.dumps({
        "spec_path": "spec.md", "tasks": [{"worker_id": "worker-1"}],
    }), encoding="utf-8")
    (run_dir / "checkpoints" / "worker-1.json").write_text(json.dumps({
        "worker_id": "worker-1", "state": "completed",
        "commit_sha": "abc1234", "files_modified": ["x.txt"],
    }), encoding="utf-8")
    (run_dir / "checkpoints" / "worker-1.progress.jsonl").write_text(
        '\n'.join([
            json.dumps({"ts": "2026-05-21T01:00:00Z", "event": "step_start", "step_id": "s1"}),
            json.dumps({"ts": "2026-05-21T01:00:05Z", "event": "step_done", "step_id": "s1"}),
        ]) + "\n",
        encoding="utf-8",
    )
    (run_dir / "notify.json").write_text(json.dumps({
        "success": True, "commit_sha": "abc1234",
    }), encoding="utf-8")
    return run_dir


def test_replay_coord_run_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        replay_coord_run("does-not-exist", runs_dir=tmp_path / "runs")


def test_replay_coord_run_assembles_report(tmp_path: Path) -> None:
    _seed_run(tmp_path, "20260521T010101-aabb")
    rep = replay_coord_run("20260521T010101-aabb", runs_dir=tmp_path / "runs")
    assert rep.state == "completed"
    assert rep.spec_path == "spec.md"
    assert len(rep.workers) == 1
    assert rep.workers[0]["worker_id"] == "worker-1"
    assert rep.total_events == 2
    assert rep.notify is not None
    assert rep.notify["success"] is True


def test_format_coord_for_human_includes_key_fields(tmp_path: Path) -> None:
    _seed_run(tmp_path, "20260521T010101-aabb")
    rep = replay_coord_run("20260521T010101-aabb", runs_dir=tmp_path / "runs")
    out = format_coord_for_human(rep)
    assert "20260521T010101-aabb" in out
    assert "worker-1" in out
    assert "abc1234" in out


def test_cli_replay_routes_run_id_to_coord(tmp_path: Path) -> None:
    """`harness replay <run_id>` triggers replay_coord_run, not replay_dispatch."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_run(iso_path, "20260521T010101-aabb")
        result = runner.invoke(cli, ["replay", "20260521T010101-aabb"])
    assert result.exit_code == 0, result.output
    assert "20260521T010101-aabb" in result.output
    assert "worker-1" in result.output


def test_cli_replay_still_handles_dispatch_id(tmp_path: Path) -> None:
    """Non-run-id strings still go through the dispatch replay path."""
    from unittest.mock import patch, MagicMock
    runner = CliRunner()
    with patch("harness.replay.replay_dispatch") as mock_rep:
        mock_rep.return_value = MagicMock(
            task_id="disp-1", summary="ok", total_elapsed_ms=42,
            final_outcome="success", events=[],
        )
        result = runner.invoke(cli, ["replay", "disp-1", "--format", "json"])
    assert result.exit_code == 0, result.output
    mock_rep.assert_called_once()
