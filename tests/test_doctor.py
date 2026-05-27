"""Tests for FIRST-RUN-DOCTOR.

P2 audit fix (2026-05-27): the three near-duplicate presence checks
(``_check_secrets`` / ``_check_engine_reachability`` /
``_check_env_var_inventory``) were collapsed into a single
``_check_engine_keys`` check; live reachability is now a separate
opt-in path via ``harness doctor --probe`` calling ``_probe_engines_live``.
Tests in this file were rewritten to match the new shape.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.doctor import (
    Diagnosis, overall_severity, run_all,
    _check_python_version, _check_coord_writable,
    _check_engine_keys, _probe_engines_live,
    _check_claude_binary,
)


# ---------------------------------------------------------------------------
# basic check primitives (unchanged across audit)
# ---------------------------------------------------------------------------


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
    # P2: collapsed `secrets` + `engine_reachability` + `env_var_inventory`
    # into a single `engine_keys` check.
    assert {"python", "git", "engine_keys", "coord_dir"} <= names


def test_run_all_default_excludes_probe_results() -> None:
    """The default ``run_all()`` must NOT do live network probes."""
    diags = run_all()
    probe_names = [d.name for d in diags if d.name.startswith("probe:")]
    assert probe_names == [], (
        "default run_all() should not call probe_engine_live; "
        "probes belong to --probe"
    )


# ---------------------------------------------------------------------------
# P2: consolidated _check_engine_keys (replaces the pre-audit triplet)
# ---------------------------------------------------------------------------


class TestCheckEngineKeys:
    def test_fail_when_no_key_anywhere(self, monkeypatch) -> None:
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                  "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)
        with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
            d = _check_engine_keys()
        assert d.severity == "fail"
        assert "no engine API keys configured" in d.message
        # Fix hint must point at keys serve (the operator-facing path)
        assert "harness keys serve" in d.fix
        # Each required var must appear in the inventory part of the message
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "MIMO_API_KEY"]:
            assert f"{k}:UNSET" in d.message

    def test_ok_when_env_var_present(self, monkeypatch) -> None:
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                  "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
        with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
            d = _check_engine_keys()
        assert d.severity == "ok"
        assert "DEEPSEEK_API_KEY:ENV" in d.message
        # Reminder about --probe must be present so operators know presence
        # ≠ reachability.
        assert "--probe" in d.message

    def test_ok_when_dpapi_key_present(self, monkeypatch) -> None:
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                  "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)
        with patch(
            "harness.secrets.dpapi.list_secrets",
            return_value=["KIMI_API_KEY", "DEEPSEEK_API_KEY"],
        ):
            d = _check_engine_keys()
        assert d.severity == "ok"
        assert "KIMI_API_KEY:DPAPI" in d.message
        assert "DEEPSEEK_API_KEY:DPAPI" in d.message

    def test_ok_with_mixed_sources(self, monkeypatch) -> None:
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                  "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "x")
        with patch(
            "harness.secrets.dpapi.list_secrets",
            return_value=["KIMI_API_KEY"],
        ):
            d = _check_engine_keys()
        assert d.severity == "ok"
        assert "KIMI_API_KEY:DPAPI" in d.message
        assert "GEMINI_API_KEY:ENV" in d.message

    def test_message_surfaces_mimo_tokenplan(self, monkeypatch) -> None:
        """The tp- / sk- MiMo prefix detection used to live in the
        old ``_check_engine_reachability``; it survives into the
        consolidated check."""
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                  "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MIMO_API_KEY", "tp-secret-do-not-log")
        with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
            d = _check_engine_keys()
        assert d.severity == "ok"
        assert "mimo=tokenplan" in d.message
        # Key value must NEVER appear in the message
        assert "tp-secret-do-not-log" not in d.message

    def test_message_surfaces_mimo_payg(self, monkeypatch) -> None:
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                  "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MIMO_API_KEY", "sk-paykey")
        with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
            d = _check_engine_keys()
        assert d.severity == "ok"
        assert "mimo=payg" in d.message
        assert "sk-paykey" not in d.message

    def test_inventory_includes_openai(self, monkeypatch) -> None:
        """OPENAI_API_KEY is in the inventory list even though it is
        not currently a probeable engine — operators should still see
        whether they have it configured."""
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                  "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("KIMI_API_KEY", "x")
        monkeypatch.setenv("OPENAI_API_KEY", "y")
        with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
            d = _check_engine_keys()
        assert "OPENAI_API_KEY:ENV" in d.message

    def test_does_not_crash_when_dpapi_unavailable(self, monkeypatch) -> None:
        """If DPAPI raises (e.g. non-Windows), the check should still
        evaluate env vars and return a sensible diagnosis."""
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                  "GEMINI_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
        with patch(
            "harness.secrets.dpapi.list_secrets",
            side_effect=NotImplementedError("non-windows"),
        ):
            d = _check_engine_keys()
        assert d.severity == "ok"
        assert "DEEPSEEK_API_KEY:ENV" in d.message


# ---------------------------------------------------------------------------
# P2: live network probe (_probe_engines_live + harness doctor --probe)
# ---------------------------------------------------------------------------


class TestProbeEnginesLive:
    def _clear_keys(self, monkeypatch) -> None:
        for k in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "MIMO_API_KEY",
                  "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)

    def test_warn_when_nothing_configured(self, monkeypatch) -> None:
        self._clear_keys(monkeypatch)
        with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
            results = _probe_engines_live()
        assert len(results) == 1
        assert results[0].name == "engine_probe"
        assert results[0].severity == "warn"
        assert "nothing to probe" in results[0].message

    def test_probes_each_configured_provider(self, monkeypatch) -> None:
        self._clear_keys(monkeypatch)
        monkeypatch.setenv("KIMI_API_KEY", "x")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "y")
        with patch(
            "harness.secrets.dpapi.list_secrets", return_value=[],
        ), patch(
            "harness.cli_helpers.probe_engine_live",
            return_value=("up", None),
        ) as mock_probe:
            results = _probe_engines_live()
        # One probe per configured key
        engines_probed = {call.args[0] for call in mock_probe.call_args_list}
        assert engines_probed == {"kimi", "deepseek"}
        # All ok
        assert all(d.severity == "ok" for d in results)
        names = {d.name for d in results}
        assert names == {"probe:kimi", "probe:deepseek"}

    def test_failed_probe_returns_fail_diagnosis(self, monkeypatch) -> None:
        self._clear_keys(monkeypatch)
        monkeypatch.setenv("MIMO_API_KEY", "x")
        with patch(
            "harness.secrets.dpapi.list_secrets", return_value=[],
        ), patch(
            "harness.cli_helpers.probe_engine_live",
            return_value=("auth", "401 Unauthorized"),
        ):
            results = _probe_engines_live()
        assert len(results) == 1
        d = results[0]
        assert d.severity == "fail"
        assert d.name == "probe:mimo"
        assert "auth" in d.message
        assert "401 Unauthorized" in d.message
        # Fix hint should point at the var name + remediation
        assert "MIMO_API_KEY" in d.fix
        assert "keys serve" in d.fix

    def test_crashing_probe_does_not_break_other_probes(
        self, monkeypatch,
    ) -> None:
        self._clear_keys(monkeypatch)
        monkeypatch.setenv("KIMI_API_KEY", "x")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "y")

        call_count = {"n": 0}

        def fake_probe(name, *, log=True, log_path=None):
            call_count["n"] += 1
            if name == "kimi":
                raise RuntimeError("transient")
            return ("up", None)

        with patch(
            "harness.secrets.dpapi.list_secrets", return_value=[],
        ), patch(
            "harness.cli_helpers.probe_engine_live", side_effect=fake_probe,
        ):
            results = _probe_engines_live()

        by_name = {d.name: d for d in results}
        assert by_name["probe:kimi"].severity == "fail"
        assert "transient" in by_name["probe:kimi"].message
        assert by_name["probe:deepseek"].severity == "ok"

    def test_run_all_with_probe_includes_probe_diagnoses(
        self, monkeypatch,
    ) -> None:
        self._clear_keys(monkeypatch)
        monkeypatch.setenv("KIMI_API_KEY", "x")
        with patch(
            "harness.secrets.dpapi.list_secrets", return_value=[],
        ), patch(
            "harness.cli_helpers.probe_engine_live",
            return_value=("up", None),
        ):
            diags = run_all(with_probe=True)
        names = {d.name for d in diags}
        assert "probe:kimi" in names


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


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


def test_cli_doctor_probe_flag_invokes_with_probe(
    tmp_path, monkeypatch,
) -> None:
    """The ``--probe`` flag must propagate to ``run_all(with_probe=True)``."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with patch(
        "harness.doctor.run_all", return_value=[Diagnosis("python", "ok", "x")],
    ) as mock_run_all:
        result = runner.invoke(cli, ["doctor", "--probe"])
    assert result.exit_code == 0
    # Confirm with_probe=True was passed
    mock_run_all.assert_called_once()
    _, kwargs = mock_run_all.call_args
    assert kwargs.get("with_probe") is True


def test_cli_doctor_no_probe_flag_means_with_probe_false(
    tmp_path, monkeypatch,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with patch(
        "harness.doctor.run_all", return_value=[Diagnosis("python", "ok", "x")],
    ) as mock_run_all:
        result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    _, kwargs = mock_run_all.call_args
    assert kwargs.get("with_probe") is False


# ---------------------------------------------------------------------------
# W14-DEPLOY-FRICTION 2026-05-26: claude binary check (pre-audit, kept)
# ---------------------------------------------------------------------------


class TestClaudeBinaryCheck:
    def test_warn_when_claude_not_on_path(self) -> None:
        with patch("harness.doctor.shutil.which", return_value=None):
            d = _check_claude_binary()
        assert d.severity == "warn"
        assert "claude CLI not found" in d.message
        assert "claude.com" in d.fix or "docs.claude" in d.fix

    def test_ok_when_claude_version_succeeds(self) -> None:
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
