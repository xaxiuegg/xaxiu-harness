"""Tests for WIRE-DB-SNAPSHOT-CRON."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner



@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()






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




