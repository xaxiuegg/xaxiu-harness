"""Tests for FIRST-RUN-DOCTOR."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.doctor import (
    Diagnosis, overall_severity, run_all,
    _check_python_version, _check_coord_writable, _check_secrets,
    _check_env_var_inventory, _check_engine_reachability,
    _check_claude_binary,
)


def test_python_check_passes_on_current_interpreter() -> None:
    d = _check_python_version()
    assert d.severity == "ok"


def test_coord_writable_creates_probe_then_cleans_up(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    d = _check_coord_writable()
    assert d.severity == "ok"
    # Probe file should be gone
    assert not (tmp_path / "coord" / ".doctor_probe").exists()


def test_overall_severity_picks_worst() -> None:
    diags = [
        Diagnosis("a", "ok", "fine"),
        Diagnosis("b", "warn", "meh"),
    ]
    assert overall_severity(diags) == "warn"
    diags.append(Diagnosis("c", "fail", "broken"))
    assert overall_severity(diags) == "fail"


def test_run_all_returns_list_of_diagnoses() -> None:
    diags = run_all()
    assert all(isinstance(d, Diagnosis) for d in diags)
    assert len(diags) >= 5
    names = {d.name for d in diags}
    assert {"python", "git", "secrets", "coord_dir"} <= names


def test_secrets_check_reports_when_env_var_present(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
        d = _check_secrets()
    assert d.severity == "ok"


def test_cli_doctor_runs(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with patch("harness.doctor.run_all", return_value=[
        Diagnosis("python", "ok", "fine"),
        Diagnosis("git", "ok", "fine"),
    ]):
        result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "overall: OK" in result.output


def test_cli_doctor_exits_1_on_fail(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with patch("harness.doctor.run_all", return_value=[
        Diagnosis("dpapi", "fail", "broken", fix="run harness install"),
    ]):
        result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 1
    assert "fix: run harness install" in result.output


def test_env_var_inventory_all_set_is_ok(monkeypatch) -> None:
    for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.setenv(k, "secret")
    d = _check_env_var_inventory()
    assert d.severity == "ok"


def test_env_var_inventory_mixed_is_ok(monkeypatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "secret")
    for k in ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    d = _check_env_var_inventory()
    assert d.severity == "ok"


def test_env_var_inventory_all_unset_is_warn(monkeypatch) -> None:
    for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    d = _check_env_var_inventory()
    assert d.severity == "warn"


def test_env_var_inventory_message_format(monkeypatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "secret_value")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "another_secret")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    d = _check_env_var_inventory()
    parts = d.message.split(", ")
    keys = [p.split(":")[0] for p in parts]
    assert keys == [
        "KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY",
    ]
    for p in parts:
        assert p.endswith(":SET") or p.endswith(":UNSET")
    assert "secret_value" not in d.message
    assert "another_secret" not in d.message


def test_engine_reachability_both_empty(monkeypatch):
    for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MIMO_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
        d = _check_engine_reachability()
    assert d.severity == "fail"
    assert "harness install" in d.fix


def test_engine_reachability_only_dpapi(monkeypatch):
    for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MIMO_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    with patch("harness.secrets.dpapi.list_secrets", return_value=["KIMI_API_KEY", "DEEPSEEK_API_KEY"]):
        d = _check_engine_reachability()
    assert d.severity == "ok"
    assert "dpapi=2" in d.message


def test_engine_reachability_only_env(monkeypatch):
    for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MIMO_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
        d = _check_engine_reachability()
    assert d.severity == "ok"
    assert "env=ANTHROPIC_API_KEY" in d.message


def test_engine_reachability_both_populated(monkeypatch):
    for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MIMO_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    with patch("harness.secrets.dpapi.list_secrets", return_value=["KIMI_API_KEY"]):
        d = _check_engine_reachability()
    assert d.severity == "ok"
    assert "dpapi=1" in d.message
    assert "env=GEMINI_API_KEY" in d.message


def test_cli_doctor_json_format(tmp_path, monkeypatch) -> None:
    import json
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with patch("harness.doctor.run_all", return_value=[
        Diagnosis("python", "ok", "fine"),
    ]):
        result = runner.invoke(cli, ["doctor", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["overall"] == "ok"
    assert data["checks"][0]["name"] == "python"


# ---------------------------------------------------------------------------
# WIRE-MIMO-DOCTOR (2026-05-22) — surface tp-/sk- MiMo key in reachability
# ---------------------------------------------------------------------------

def test_engine_reachability_surfaces_mimo_tokenplan(monkeypatch) -> None:
    for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MIMO_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MIMO_API_KEY", "tp-secret")
    with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
        d = _check_engine_reachability()
    assert d.severity == "ok"
    assert "mimo=tokenplan" in d.message
    # never leak the actual key
    assert "tp-secret" not in d.message


def test_engine_reachability_surfaces_mimo_payg(monkeypatch) -> None:
    for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MIMO_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MIMO_API_KEY", "sk-paykey")
    with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
        d = _check_engine_reachability()
    assert d.severity == "ok"
    assert "mimo=payg" in d.message
    assert "sk-paykey" not in d.message


# ---------------------------------------------------------------------------
# W14-DEPLOY-FRICTION 2026-05-26: claude binary check
# ---------------------------------------------------------------------------


class TestClaudeBinaryCheck:
    def test_warn_when_claude_not_on_path(self) -> None:
        # Mock shutil.which to return None
        with patch("harness.doctor.shutil.which", return_value=None):
            d = _check_claude_binary()
        assert d.severity == "warn"
        assert "claude CLI not found" in d.message
        assert "claude.com" in d.fix or "docs.claude" in d.fix

    def test_ok_when_claude_version_succeeds(self) -> None:
        # Mock shutil.which to return a path + subprocess.run to succeed
        fake_result = MagicMock()
        fake_result.stdout = "1.2.3 (Claude Code)\n"
        with patch(
            "harness.doctor.shutil.which", return_value="/usr/bin/claude",
        ), patch(
            "harness.doctor.subprocess.run", return_value=fake_result,
        ):
            d = _check_claude_binary()
        assert d.severity == "ok"
        assert "1.2.3" in d.message

    def test_warn_when_version_probe_fails(self) -> None:
        with patch(
            "harness.doctor.shutil.which", return_value="/usr/bin/claude",
        ), patch(
            "harness.doctor.subprocess.run",
            side_effect=RuntimeError("crashed"),
        ):
            d = _check_claude_binary()
        assert d.severity == "warn"
        assert "--version failed" in d.message

    def test_doctor_run_all_includes_claude_check(self) -> None:
        diags = run_all()
        names = {d.name for d in diags}
        assert "claude_binary" in names

    def test_doctor_cli_surfaces_claude_check(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        # Don't assert on exit code (depends on whether claude is
        # actually installed on the test machine) — just that the
        # check ran + appears in output
        assert "claude_binary" in result.output
