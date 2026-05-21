"""Tests for harness.loops.scheduler — Windows Task Scheduler integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from harness.loops import scheduler


class TestRegister:
    def test_register_returns_true_on_ok(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value="powershell.exe"), \
             patch("harness.loops.scheduler.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
            ok, msg = scheduler.register_loop_task(cadence_minutes=30)
        assert ok is True
        assert "30 min" in msg

    def test_register_returns_false_when_no_powershell(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value=None):
            ok, msg = scheduler.register_loop_task()
        assert ok is False
        assert "PowerShell not found" in msg

    def test_register_returns_false_on_subprocess_failure(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value="powershell.exe"), \
             patch("harness.loops.scheduler.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="Access denied"
            )
            ok, msg = scheduler.register_loop_task()
        assert ok is False
        assert "Access denied" in msg


class TestUnregister:
    def test_unregister_success(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value="powershell.exe"), \
             patch("harness.loops.scheduler.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="OK removed", stderr=""
            )
            ok, msg = scheduler.unregister_loop_task()
        assert ok is True
        assert "removed" in msg.lower()

    def test_unregister_no_powershell(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value=None):
            ok, msg = scheduler.unregister_loop_task()
        assert ok is False
        assert "PowerShell not found" in msg


class TestIsRegistered:
    def test_returns_true_when_yes(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value="powershell.exe"), \
             patch("harness.loops.scheduler.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="YES\n")
            assert scheduler.is_registered() is True

    def test_returns_false_when_no(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value="powershell.exe"), \
             patch("harness.loops.scheduler.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="NO\n")
            assert scheduler.is_registered() is False

    def test_returns_false_when_no_powershell(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value=None):
            assert scheduler.is_registered() is False
