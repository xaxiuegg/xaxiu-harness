"""Tests for harness.loops.scheduler — Windows Task Scheduler integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.loops import scheduler


class TestHelpers:
    def test_pwsh_returns_pwsh_when_available(self) -> None:
        with patch(
            "harness.loops.scheduler.shutil.which",
            side_effect=lambda name: "/usr/bin/pwsh" if name == "pwsh" else None,
        ):
            assert scheduler._pwsh() == "/usr/bin/pwsh"

    def test_pwsh_falls_back_to_powershell(self) -> None:
        with patch(
            "harness.loops.scheduler.shutil.which",
            side_effect=lambda name: "/bin/powershell" if name == "powershell" else None,
        ):
            assert scheduler._pwsh() == "/bin/powershell"

    def test_pwsh_returns_none_when_neither_available(self) -> None:
        with patch("harness.loops.scheduler.shutil.which", return_value=None):
            assert scheduler._pwsh() is None

    def test_loop_tick_cmd_uses_venv_python_when_exists(self, tmp_path: Path) -> None:
        venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
        with patch("harness.loops.scheduler._REPO_ROOT", tmp_path):
            cmd = scheduler._loop_tick_cmd()
        assert str(venv_python) in cmd
        assert cmd.endswith(" -m harness loop tick")

    def test_loop_tick_cmd_falls_back_to_plain_python(self, tmp_path: Path) -> None:
        with patch("harness.loops.scheduler._REPO_ROOT", tmp_path):
            cmd = scheduler._loop_tick_cmd()
        assert cmd == "python -m harness loop tick"

    def test_build_register_script_contains_repetition_interval(self) -> None:
        script = scheduler._build_register_script(42)
        assert "RepetitionInterval (New-TimeSpan -Minutes 42)" in script

    def test_build_register_script_contains_try_catch(self) -> None:
        script = scheduler._build_register_script(30)
        assert "try {" in script
        assert "catch {" in script

    def test_build_register_script_uses_runlevel_limited(self) -> None:
        script = scheduler._build_register_script(30)
        assert "-RunLevel Limited" in script


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

    def test_register_propagates_nonzero_returncode_empty_streams(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value="powershell.exe"), \
             patch("harness.loops.scheduler.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            ok, msg = scheduler.register_loop_task()
        assert ok is False
        assert msg == "unknown error"


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

    def test_unregister_task_not_found(self) -> None:
        with patch("harness.loops.scheduler._pwsh", return_value="powershell.exe"), \
             patch("harness.loops.scheduler.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="SKIP not found", stderr=""
            )
            ok, msg = scheduler.unregister_loop_task()
        assert ok is True
        assert "not found" in msg.lower()


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
