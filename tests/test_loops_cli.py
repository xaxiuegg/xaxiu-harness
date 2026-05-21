"""Tests for the `harness loop` CLI verb group (Wave 6/B)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestLoopGroup:
    def test_loop_help_lists_subcommands(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["loop", "--help"])
        assert result.exit_code == 0
        for sub in ("init", "tick", "start", "stop", "status"):
            assert sub in result.output


class TestLoopInit:
    def test_init_creates_state(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "coord" / "dev_loop" / "state.json"
        result = runner.invoke(cli, ["loop", "init", "--state-path", str(target)])
        assert result.exit_code == 0
        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["loop_status"] == "armed"

    def test_init_idempotent(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text('{"loop_status":"armed"}', encoding="utf-8")
        result = runner.invoke(cli, ["loop", "init", "--state-path", str(target)])
        assert result.exit_code == 0
        assert "already exists" in result.output.lower()


class TestLoopTick:
    def test_tick_against_fresh_state(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        runner.invoke(cli, ["loop", "init", "--state-path", str(target)])
        # Need a tests/ subdir for the testing supervisor's project root check
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        result = runner.invoke(
            cli,
            [
                "loop", "tick",
                "--state-path", str(target),
                "--project-root", str(tmp_path),
            ],
        )
        # tick may run testing supervisor; either pass or escalate is OK,
        # but the verb must exit cleanly.
        assert result.exit_code in (0, 1)
        assert "tick #" in result.output


class TestLoopStatus:
    def test_status_against_existing_state(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        runner.invoke(cli, ["loop", "init", "--state-path", str(target)])
        with patch("harness.loops.scheduler.is_registered", return_value=False):
            result = runner.invoke(cli, ["loop", "status", "--state-path", str(target)])
        assert result.exit_code == 0
        assert "loop:" in result.output
        assert "scheduled=no" in result.output


class TestLoopSchedulerCalls:
    def test_start_calls_register(self, runner: CliRunner) -> None:
        with patch("harness.loops.scheduler.register_loop_task",
                   return_value=(True, "ok")) as mock:
            result = runner.invoke(cli, ["loop", "start", "--cadence-minutes", "45"])
        assert result.exit_code == 0
        mock.assert_called_once_with(cadence_minutes=45)
        assert "ok" in result.output

    def test_start_failure_exits_nonzero(self, runner: CliRunner) -> None:
        with patch("harness.loops.scheduler.register_loop_task",
                   return_value=(False, "nope")):
            result = runner.invoke(cli, ["loop", "start"])
        assert result.exit_code == 1
        assert "nope" in result.output

    def test_stop_calls_unregister(self, runner: CliRunner) -> None:
        with patch("harness.loops.scheduler.unregister_loop_task",
                   return_value=(True, "removed")) as mock:
            result = runner.invoke(cli, ["loop", "stop"])
        assert result.exit_code == 0
        mock.assert_called_once_with()
        assert "removed" in result.output
