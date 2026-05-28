"""Tests for WIRE-OBSERVER-AUTOARM-ALL — `observer install-scheduler --all`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_install_scheduler_no_all_only_arms_observer(runner: CliRunner) -> None:
    """Without --all, only the observer+retro tasks are armed."""
    with patch("harness.cli.register_tasks",
               return_value=(True, "armed")) as mock_reg:
        result = runner.invoke(cli, ["observer", "install-scheduler"])
    assert result.exit_code == 0
    assert "observer/retro:" in result.output
    mock_reg.assert_called_once()
    # No mention of downstream tasks in default output
    assert "db-snapshot" not in result.output
    assert "cost-export" not in result.output


def test_install_scheduler_all_implies_include_chat(runner: CliRunner) -> None:
    """--all flag implies --include-chat."""
    with patch("harness.cli.register_tasks",
               return_value=(True, "armed")) as mock_reg:
        try:
            from harness.state import db_scheduler
            with patch.object(db_scheduler, "register_snapshot_task",
                              return_value=(True, "OK")):
                result = runner.invoke(cli, ["observer", "install-scheduler", "--all"])
        except ImportError:
            result = runner.invoke(cli, ["observer", "install-scheduler", "--all"])
    assert result.exit_code == 0
    # register_tasks was called with include_chat=True
    assert mock_reg.call_args.kwargs.get("include_chat") is True


def test_install_scheduler_all_arms_db_snapshot(runner: CliRunner) -> None:
    """With --all, the db-snapshot task is registered.

    W14-REPO-WIDE-STALENESS-AUDIT 2026-05-28: removed the stale
    ``pytest.skip("db_scheduler module not yet shipped")`` guard —
    ``harness.state.db_scheduler`` has been in the tree for weeks
    and imports cleanly.  The skip path was dead code.
    """
    from harness.state import db_scheduler  # noqa: F401
    with patch("harness.cli.register_tasks",
               return_value=(True, "armed")), \
         patch("harness.state.db_scheduler.register_snapshot_task",
               return_value=(True, "OK")) as mock_db:
        result = runner.invoke(cli, ["observer", "install-scheduler", "--all"])
    assert result.exit_code == 0
    assert "db-snapshot:" in result.output
    mock_db.assert_called_once()


def test_uninstall_scheduler_removes_observer_at_minimum(runner: CliRunner) -> None:
    with patch("harness.cli.unregister_tasks",
               return_value=(True, "removed")):
        result = runner.invoke(cli, ["observer", "uninstall-scheduler"])
    assert result.exit_code == 0
    assert "observer/retro: removed" in result.output


def test_install_scheduler_all_handles_partial_failure(runner: CliRunner) -> None:
    """When db-snapshot registration fails, --all still attempts cost-export
    and exits 1 to surface the failure.

    W14-REPO-WIDE-STALENESS-AUDIT 2026-05-28: see the partner test
    above — same stale skip removed here.
    """
    from harness.state import db_scheduler  # noqa: F401
    with patch("harness.cli.register_tasks",
               return_value=(True, "armed")), \
         patch("harness.state.db_scheduler.register_snapshot_task",
               return_value=(False, "FAIL: access denied")):
        result = runner.invoke(cli, ["observer", "install-scheduler", "--all"])
    assert result.exit_code == 1
    assert "db-snapshot:" in result.output
    assert "FAIL" in result.output
