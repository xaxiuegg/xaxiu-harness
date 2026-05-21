"""Tests for CHAT-OBSERVER-AUTO-ARM registration."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from click.testing import CliRunner
from harness.cli import cli


# ---------------------------------------------------------------------------
# register_chat_audit_task
# ---------------------------------------------------------------------------


def test_register_chat_audit_task_returns_true_on_success() -> None:
    """register_chat_audit_task invokes PowerShell + returns True on rc=0."""
    from harness.observer import scheduler

    with patch.object(scheduler, "subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
        ok = scheduler.register_chat_audit_task(cadence_minutes=30)
        assert ok is True
        called = mock_sub.run.call_args
        # The PS command should mention "audit-chat" so we know it's the right task
        cmd_str = " ".join(str(x) for x in called[0][0])
        assert "audit-chat" in cmd_str


def test_register_chat_audit_task_returns_false_on_failure() -> None:
    from harness.observer import scheduler

    with patch.object(scheduler, "subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=1, stdout="", stderr="ACCESS DENIED")
        ok = scheduler.register_chat_audit_task()
        assert ok is False


# ---------------------------------------------------------------------------
# register_tasks include_chat integration
# ---------------------------------------------------------------------------


def test_register_tasks_with_include_chat_calls_chat_helper() -> None:
    from harness.observer.scheduler import register_tasks

    with patch("harness.observer.scheduler._pwsh", return_value="powershell.exe"), \
         patch("harness.observer.scheduler.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="OK\n", stderr=""),   # cycle
            MagicMock(returncode=0, stdout="OK\n", stderr=""),   # retro
            MagicMock(returncode=0, stdout="OK\n", stderr=""),   # chat audit
        ]
        ok, msg = register_tasks(cadence_minutes=45, include_chat=True)
    assert ok is True
    assert "45 min" in msg
    assert "chat audit registered" in msg


def test_register_tasks_with_include_chat_failure_reported() -> None:
    from harness.observer.scheduler import register_tasks

    with patch("harness.observer.scheduler._pwsh", return_value="powershell.exe"), \
         patch("harness.observer.scheduler.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="OK\n", stderr=""),   # cycle ok
            MagicMock(returncode=0, stdout="OK\n", stderr=""),   # retro ok
            MagicMock(returncode=1, stdout="CHAT_FAIL", stderr=""),  # chat fail
        ]
        ok, msg = register_tasks(include_chat=True)
    assert ok is False
    assert "chat audit failed" in msg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_observer_install_scheduler_include_chat_flag() -> None:
    """`harness observer install-scheduler --include-chat` triggers chat task registration."""
    with patch("harness.cli.register_tasks") as mock_reg:
        mock_reg.return_value = (True, "ok")
        runner = CliRunner()
        result = runner.invoke(cli, ["observer", "install-scheduler", "--include-chat"])
    assert result.exit_code == 0, result.output
    mock_reg.assert_called_once_with(cadence_minutes=60, daily_time="23:00", include_chat=True)


def test_cli_observer_install_scheduler_no_chat_by_default() -> None:
    """`harness observer install-scheduler` does not register chat audit by default."""
    with patch("harness.cli.register_tasks") as mock_reg:
        mock_reg.return_value = (True, "ok")
        runner = CliRunner()
        result = runner.invoke(cli, ["observer", "install-scheduler"])
    assert result.exit_code == 0, result.output
    mock_reg.assert_called_once_with(cadence_minutes=60, daily_time="23:00", include_chat=False)


# ---------------------------------------------------------------------------
# Unregister includes chat task
# ---------------------------------------------------------------------------


def test_unregister_tasks_includes_chat_audit() -> None:
    from harness.observer.scheduler import unregister_tasks

    with patch("harness.observer.scheduler._pwsh", return_value="powershell.exe"), \
         patch("harness.observer.scheduler.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="OK removed cycle", stderr=""),
            MagicMock(returncode=0, stdout="OK removed retro", stderr=""),
            MagicMock(returncode=0, stdout="OK removed chat", stderr=""),
        ]
        ok, msg = unregister_tasks()
    assert ok is True
    assert "OK removed cycle" in msg
    assert "OK removed retro" in msg
    assert "OK removed chat" in msg
