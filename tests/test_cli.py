"""Tests for the xaxiu-harness CLI using click.testing.CliRunner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def test_dispatch_missing_args(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["dispatch"])
    assert result.exit_code == 2
    assert "error: --project and --packet are required" in result.output


@patch("harness.cli.dispatch_packet")
def test_dispatch_success(mock_dispatch, runner: CliRunner) -> None:
    mock_dispatch.return_value = MagicMock(
        success=True, text="ok", error=None, fallback_chain=[]
    )
    result = runner.invoke(cli, ["dispatch", "-p", "myproj", "--packet", "p.md"])
    assert result.exit_code == 0
    assert "ok" in result.output
    mock_dispatch.assert_called_once_with(
        project="myproj", packet_path="p.md", force_engine=None, force_model=None
    )


@patch("harness.cli.dispatch_packet")
def test_dispatch_failure(mock_dispatch, runner: CliRunner) -> None:
    mock_dispatch.return_value = MagicMock(
        success=False, text="", error="boom", fallback_chain=["kimi"]
    )
    result = runner.invoke(cli, ["dispatch", "-p", "myproj", "--packet", "p.md"])
    assert result.exit_code == 1
    assert "error: boom" in result.output


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@patch("harness.cli._repo_root")
@patch("harness.cli.load_template")
def test_init_success(mock_load_template, mock_repo_root, runner: CliRunner, tmp_path: Path) -> None:
    from harness.adapters.schema import AdapterConfig, StatusTrackingConfig, ObserverConfig

    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    mock_repo_root.return_value = tmp_path

    cfg = AdapterConfig(
        name="demo",
        project_root=str(tmp_path / "project"),
        status_tracking=StatusTrackingConfig(backend="csv", config={"csv_path": "STATUS.csv"}),
        observer=ObserverConfig(),
    )
    mock_load_template.return_value = cfg

    result = runner.invoke(cli, ["init", "-p", "myproj", "-t", "warehouse-style"])
    assert result.exit_code == 0
    assert "harness-adapter.yaml" in result.output

    adapter_path = adapters_dir / "myproj" / "harness-adapter.yaml"
    assert adapter_path.exists()
    data = yaml.safe_load(adapter_path.read_text())
    assert data["name"] == "myproj"
    mock_load_template.assert_called_once_with("warehouse-style")


@patch("harness.cli._repo_root")
@patch("harness.cli.load_template")
def test_init_refuses_overwrite(mock_load_template, mock_repo_root, runner: CliRunner, tmp_path: Path) -> None:
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    mock_repo_root.return_value = tmp_path

    # Pre-create the adapter file
    existing = adapters_dir / "myproj" / "harness-adapter.yaml"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("{}", encoding="utf-8")

    result = runner.invoke(cli, ["init", "-p", "myproj", "-t", "warehouse-style"])
    assert result.exit_code == 2
    assert "already exists" in result.output
    mock_load_template.assert_not_called()


@patch("harness.cli._repo_root")
@patch("harness.cli.load_template")
def test_init_force_overwrite(mock_load_template, mock_repo_root, runner: CliRunner, tmp_path: Path) -> None:
    from harness.adapters.schema import AdapterConfig, StatusTrackingConfig, ObserverConfig

    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    mock_repo_root.return_value = tmp_path

    existing = adapters_dir / "myproj" / "harness-adapter.yaml"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("{}", encoding="utf-8")

    cfg = AdapterConfig(
        name="demo",
        project_root=str(tmp_path / "project"),
        status_tracking=StatusTrackingConfig(backend="csv", config={"csv_path": "STATUS.csv"}),
        observer=ObserverConfig(),
    )
    mock_load_template.return_value = cfg

    result = runner.invoke(cli, ["init", "-p", "myproj", "-t", "warehouse-style", "--force"])
    assert result.exit_code == 0
    data = yaml.safe_load(existing.read_text())
    assert data["name"] == "myproj"


@patch("harness.cli.load_template")
def test_init_template_not_found(mock_load_template, runner: CliRunner) -> None:
    mock_load_template.side_effect = FileNotFoundError("templates/warehouse-style.yaml")
    result = runner.invoke(cli, ["init", "-p", "myproj", "-t", "warehouse-style"])
    assert result.exit_code == 1
    assert "error:" in result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@patch("harness.cli.load_project_adapter")
def test_status_report_missing_project(mock_load_project_adapter, runner: CliRunner) -> None:
    result = runner.invoke(cli, ["status", "report"])
    assert result.exit_code == 2
    assert "error: --project is required" in result.output
    mock_load_project_adapter.assert_not_called()


@patch("harness.cli.load_project_adapter")
def test_status_report_adapter_not_found(mock_load_project_adapter, runner: CliRunner) -> None:
    mock_load_project_adapter.side_effect = FileNotFoundError("adapter missing")
    result = runner.invoke(cli, ["status", "report", "-p", "badproj"])
    assert result.exit_code == 1
    assert "error:" in result.output


@patch("harness.cli.load_project_adapter")
def test_status_report_csv_success(mock_load_project_adapter, runner: CliRunner, tmp_path: Path) -> None:
    from harness.adapters.schema import AdapterConfig, StatusTrackingConfig, ObserverConfig

    csv_file = tmp_path / "STATUS.csv"
    csv_file.write_text("task,status\nfoo,DONE\n", encoding="utf-8")

    cfg = AdapterConfig(
        name="myproj",
        project_root=str(tmp_path),
        status_tracking=StatusTrackingConfig(backend="csv", config={"csv_path": "STATUS.csv"}),
        observer=ObserverConfig(),
    )
    mock_load_project_adapter.return_value = cfg

    result = runner.invoke(cli, ["status", "report", "-p", "myproj"])
    assert result.exit_code == 0
    assert "task,status" in result.output


@patch("harness.cli.load_project_adapter")
def test_status_report_json_success(mock_load_project_adapter, runner: CliRunner, tmp_path: Path) -> None:
    from harness.adapters.schema import AdapterConfig, StatusTrackingConfig, ObserverConfig

    csv_file = tmp_path / "STATUS.csv"
    csv_file.write_text("task,status\nfoo,DONE\n", encoding="utf-8")

    cfg = AdapterConfig(
        name="myproj",
        project_root=str(tmp_path),
        status_tracking=StatusTrackingConfig(backend="csv", config={"csv_path": "STATUS.csv"}),
        observer=ObserverConfig(),
    )
    mock_load_project_adapter.return_value = cfg

    result = runner.invoke(cli, ["status", "report", "-p", "myproj", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["project"] == "myproj"
    assert len(payload["rows"]) == 1


# ---------------------------------------------------------------------------
# engines
# ---------------------------------------------------------------------------


@patch("harness.cli.read_engine_health")
def test_engines_list(mock_read_engine_health, runner: CliRunner) -> None:
    from harness.state.files import EngineHealth

    mock_read_engine_health.return_value = {
        "deepseek": EngineHealth(priority="HIGH", locked=True, status="up"),
    }
    result = runner.invoke(cli, ["engines", "--list"])
    assert result.exit_code == 0
    assert "deepseek: priority=HIGH locked=True status=up" in result.output
    assert "kimi: priority=NORMAL locked=False status=up" in result.output


@patch("harness.cli.probe_all_engines")
def test_engines_health(mock_probe, runner: CliRunner) -> None:
    mock_probe.return_value = {
        "deepseek": ("up", None),
        "kimi": ("down", "No API key for kimi. Run `harness env` to verify."),
        "anthropic": ("down", "network"),
    }
    result = runner.invoke(cli, ["engines", "--health"])
    assert result.exit_code == 0
    assert "deepseek: up" in result.output
    assert "kimi: down (No API key" in result.output
    assert "anthropic: down (network)" in result.output


# ---------------------------------------------------------------------------
# priority
# ---------------------------------------------------------------------------


@patch("harness.cli.update_engine_health")
def test_priority_success(mock_update, runner: CliRunner) -> None:
    result = runner.invoke(cli, ["priority", "kimi", "HIGH"])
    assert result.exit_code == 0
    assert "priority: kimi -> HIGH" in result.output
    mock_update.assert_called_once_with("kimi", {"priority": "HIGH"})


@patch("harness.cli.update_engine_health")
def test_priority_failure(mock_update, runner: CliRunner) -> None:
    mock_update.side_effect = RuntimeError("disk full")
    result = runner.invoke(cli, ["priority", "kimi", "HIGH"])
    assert result.exit_code == 1
    assert "error: disk full" in result.output


# ---------------------------------------------------------------------------
# burst
# ---------------------------------------------------------------------------


@patch("harness.cli.update_engine_health")
def test_burst_success(mock_update, runner: CliRunner) -> None:
    result = runner.invoke(cli, ["burst", "deepseek", "30"])
    assert result.exit_code == 0
    assert "burst: deepseek until" in result.output
    assert "deepseek" == result.output.split()[1]
    mock_update.assert_called_once()
    call_args = mock_update.call_args
    assert call_args[0][0] == "deepseek"
    assert call_args[0][1]["burst_until"].startswith("20")


@patch("harness.cli.update_engine_health")
def test_burst_invalid_duration(mock_update, runner: CliRunner) -> None:
    result = runner.invoke(cli, ["burst", "deepseek", "0"])
    assert result.exit_code == 2
    assert "duration_min must be positive" in result.output
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# lock
# ---------------------------------------------------------------------------


@patch("harness.cli.update_engine_health")
def test_lock_success(mock_update, runner: CliRunner) -> None:
    result = runner.invoke(cli, ["lock", "anthropic"])
    assert result.exit_code == 0
    assert "lock: anthropic locked" in result.output
    mock_update.assert_called_once_with("anthropic", {"locked": True})


@patch("harness.cli.update_engine_health")
def test_lock_release(mock_update, runner: CliRunner) -> None:
    result = runner.invoke(cli, ["lock", "anthropic", "--release"])
    assert result.exit_code == 0
    assert "lock: anthropic released" in result.output
    mock_update.assert_called_once_with("anthropic", {"locked": False})


# ---------------------------------------------------------------------------
# stubs (exit code 1)
# ---------------------------------------------------------------------------


def test_observer_group_exists(runner: CliRunner) -> None:
    """The observer-tick stub was replaced by the observer group (#20)."""
    result = runner.invoke(cli, ["observer", "--help"])
    assert result.exit_code == 0
    assert "observer" in result.output.lower()


def test_retro_stub(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["retro"])
    assert result.exit_code == 1
    assert "pending Wave A.2" in result.output


def test_install_stub(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["install"])
    assert result.exit_code == 1
    assert "pending Wave 4" in result.output


def test_dashboard_serve_stub(runner: CliRunner) -> None:
    with patch("harness.dashboard.server.serve") as mock_serve:
        result = runner.invoke(cli, ["dashboard-serve"])
        assert result.exit_code == 0
        mock_serve.assert_called_once_with(host="127.0.0.1", port=7878)


def test_loops_stub(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["loops"])
    assert result.exit_code == 1
    assert "pending scheduler integration" in result.output
