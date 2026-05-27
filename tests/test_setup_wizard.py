"""W14-HARNESS-SETUP 2026-05-26: tests for the interactive setup wizard."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.doctor import Diagnosis
from harness.setup_wizard import (
    _step_claude_binary,
    _step_doctor,
    _step_keys,
    _step_smoke_dispatch,
    _step_wrappers,
    run_wizard,
)


# ---------------------------------------------------------------------------
# Individual step functions
# ---------------------------------------------------------------------------


class TestStepDoctor:
    def test_all_ok_reports_no_issues(self) -> None:
        with patch(
            "harness.doctor.run_all",
            return_value=[
                Diagnosis("python", "ok", "fine"),
                Diagnosis("git", "ok", "fine"),
            ],
        ):
            runner = CliRunner()
            with runner.isolation():
                any_issues, by_name = _step_doctor(non_interactive=True)
        assert any_issues is False
        assert "python" in by_name

    def test_warn_or_fail_reports_issues(self) -> None:
        with patch(
            "harness.doctor.run_all",
            return_value=[
                Diagnosis("python", "ok", "fine"),
                Diagnosis("secrets", "fail", "no keys", fix="set KIMI_API_KEY"),
            ],
        ):
            runner = CliRunner()
            with runner.isolation():
                any_issues, by_name = _step_doctor(non_interactive=True)
        assert any_issues is True
        assert by_name["secrets"].severity == "fail"


class TestStepClaudeBinary:
    def test_skips_when_claude_ok(self) -> None:
        # When doctor said claude_binary is OK, this step is silent
        diag = {"claude_binary": Diagnosis("claude_binary", "ok", "fine")}
        runner = CliRunner()
        with runner.isolation():
            _step_claude_binary(diag, non_interactive=True)
        # No assertion needed — just verifying no crash + no prompt

    def test_shows_install_hint_when_missing(self) -> None:
        diag = {"claude_binary": Diagnosis(
            "claude_binary", "warn", "not found",
            fix="install from claude.com",
        )}
        runner = CliRunner()
        with runner.isolation():
            _step_claude_binary(diag, non_interactive=True)


class TestStepKeys:
    def test_skips_when_keys_already_set(self) -> None:
        diag = {"secrets": Diagnosis("secrets", "ok", "env=KIMI_API_KEY")}
        runner = CliRunner()
        with runner.isolation():
            _step_keys(diag, non_interactive=True)

    def test_non_interactive_does_not_launch_ui(self) -> None:
        diag = {"secrets": Diagnosis("secrets", "fail", "no keys")}
        with patch("harness.keys_ui.serve_key_ui") as mock_serve:
            runner = CliRunner()
            with runner.isolation():
                _step_keys(diag, non_interactive=True)
        # Non-interactive mode should not call serve_key_ui
        mock_serve.assert_not_called()


class TestStepWrappers:
    def test_skips_when_all_installed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # All wrappers already installed
        with patch(
            "harness.engines.wrapper_scripts.list_wrappers",
            return_value=[
                {"name": "claude-mimo", "installed": True,
                 "description": "x", "key_present": True},
                {"name": "claude-kimi", "installed": True,
                 "description": "x", "key_present": True},
            ],
        ):
            runner = CliRunner()
            with runner.isolation():
                _step_wrappers(non_interactive=True)

    def test_non_interactive_does_not_install(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Some wrappers missing; non-interactive mode skips
        with patch(
            "harness.engines.wrapper_scripts.list_wrappers",
            return_value=[
                {"name": "claude-mimo", "installed": False,
                 "description": "x", "key_present": True},
            ],
        ), patch(
            "harness.engines.wrapper_scripts.install_wrappers",
        ) as mock_install:
            runner = CliRunner()
            with runner.isolation():
                _step_wrappers(non_interactive=True)
        mock_install.assert_not_called()


class TestStepSmokeDispatch:
    def test_skips_when_claude_missing(self) -> None:
        diag = {"claude_binary": Diagnosis(
            "claude_binary", "warn", "missing",
        )}
        runner = CliRunner()
        with runner.isolation():
            result = _step_smoke_dispatch(diag, non_interactive=True)
        assert result is False

    def test_skips_when_no_keys(self) -> None:
        diag = {
            "claude_binary": Diagnosis("claude_binary", "ok", "fine"),
            "secrets": Diagnosis("secrets", "fail", "no keys"),
        }
        runner = CliRunner()
        with runner.isolation():
            result = _step_smoke_dispatch(diag, non_interactive=True)
        assert result is False

    def test_non_interactive_skips_real_dispatch(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Even with everything green, non-interactive avoids the
        # actual dispatch (could be slow + cost money)
        diag = {
            "claude_binary": Diagnosis("claude_binary", "ok", "fine"),
            "secrets": Diagnosis("secrets", "ok", "have keys"),
        }
        monkeypatch.setenv("MIMO_API_KEY", "tp-fake")
        with patch("harness.engines.concrete.get_engine") as mock_get:
            runner = CliRunner()
            with runner.isolation():
                result = _step_smoke_dispatch(diag, non_interactive=True)
        mock_get.assert_not_called()
        assert result is False


# ---------------------------------------------------------------------------
# Full wizard run
# ---------------------------------------------------------------------------


class TestRunWizard:
    def test_runs_non_interactively_no_crash(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Mock everything that could prompt / dispatch
        with patch(
            "harness.doctor.run_all",
            return_value=[
                Diagnosis("python", "ok", "fine"),
                Diagnosis("git", "ok", "fine"),
                Diagnosis("claude_binary", "ok", "fine"),
                Diagnosis("secrets", "ok", "have keys"),
            ],
        ):
            runner = CliRunner()
            with runner.isolation():
                rc = run_wizard(non_interactive=True)
        assert rc == 0

    def test_returns_nonzero_when_issues(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with patch(
            "harness.doctor.run_all",
            return_value=[
                Diagnosis("python", "ok", "fine"),
                Diagnosis("secrets", "fail", "no keys"),
            ],
        ):
            runner = CliRunner()
            with runner.isolation():
                rc = run_wizard(non_interactive=True)
        assert rc == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestSetupCli:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--help"])
        assert result.exit_code == 0
        assert "setup wizard" in result.output.lower() or \
               "onboarding" in result.output.lower()

    def test_non_interactive_runs_all_ok(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with patch(
            "harness.doctor.run_all",
            return_value=[
                Diagnosis("python", "ok", "fine"),
                Diagnosis("claude_binary", "ok", "claude 1.0"),
                Diagnosis("secrets", "ok", "env=KIMI_API_KEY"),
            ],
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli, ["setup", "--non-interactive"],
            )
        # Should complete successfully when doctor is all-OK
        assert "setup wizard" in result.output.lower()
        assert "complete" in result.output.lower()

    def test_non_interactive_with_issues_exits_nonzero(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with patch(
            "harness.doctor.run_all",
            return_value=[
                Diagnosis("python", "ok", "fine"),
                Diagnosis("secrets", "fail", "no keys",
                          fix="set keys"),
            ],
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli, ["setup", "--non-interactive"],
            )
        assert result.exit_code == 1
