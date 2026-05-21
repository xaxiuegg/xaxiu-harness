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
