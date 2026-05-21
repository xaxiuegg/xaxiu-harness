"""Tests for WIRE-DB-SNAPSHOT-CRON."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_state_snapshot_taken(runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
    from harness.state import db as db_module
    monkeypatch.setattr(db_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(db_module, "_connection", None)
    db_path = tmp_path / "history.db"
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE x (id INTEGER);")
    conn.commit()
    conn.close()
    result = runner.invoke(cli, ["state", "snapshot", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "snapshot:" in result.output


def test_cli_state_snapshot_missing_db_exits_1(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, [
        "state", "snapshot", "--db-path", str(tmp_path / "nope.db"),
    ])
    assert result.exit_code == 1
    assert "no snapshot" in result.output


def test_register_snapshot_task_ok() -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "_pwsh", return_value="powershell.exe"), \
         patch.object(db_scheduler, "subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
        ok, msg = db_scheduler.register_snapshot_task(cadence_minutes=30)
    assert ok is True
    assert "OK" in msg


def test_register_snapshot_task_no_pwsh() -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "_pwsh", return_value=None):
        ok, msg = db_scheduler.register_snapshot_task()
    assert ok is False
    assert "PowerShell not found" in msg


def test_unregister_snapshot_task_ok() -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "_pwsh", return_value="powershell.exe"), \
         patch.object(db_scheduler, "subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0, stdout="OK removed\n", stderr="")
        ok, msg = db_scheduler.unregister_snapshot_task()
    assert ok is True


def test_cli_state_snapshot_schedule(runner: CliRunner) -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "register_snapshot_task",
                      return_value=(True, "OK")):
        result = runner.invoke(cli, ["state", "snapshot-schedule",
                                     "--cadence-minutes", "60"])
    assert result.exit_code == 0


def test_cli_state_snapshot_unschedule(runner: CliRunner) -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "unregister_snapshot_task",
                      return_value=(True, "OK removed")):
        result = runner.invoke(cli, ["state", "snapshot-unschedule"])
    assert result.exit_code == 0
