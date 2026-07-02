"""Tests for the xaxiu-harness CLI using click.testing.CliRunner."""

from __future__ import annotations

from unittest.mock import patch


import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------










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
    # W13-ENGINE-FAILURE-VISIBILITY: ``engines --health`` now defaults to a
    # live dispatch probe.  This test continues to exercise the legacy
    # shallow probe via the ``--shallow`` flag.  See
    # tests/test_engine_failure_visibility.py for live-probe coverage.
    mock_probe.return_value = {
        "deepseek": ("up", None),
        "kimi": ("down", "No API key for kimi. Run `harness env` to verify."),
        "anthropic": ("down", "network"),
    }
    result = runner.invoke(cli, ["engines", "--health", "--shallow"])
    assert result.exit_code == 0
    assert "deepseek: up" in result.output
    assert "kimi: down (No API key" in result.output
    assert "anthropic: down (network)" in result.output


# ---------------------------------------------------------------------------
# priority
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# burst
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# lock
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# stubs (exit code 1)
# ---------------------------------------------------------------------------


# PATH-A-TRIM 2026-05-29: test_observer_group_exists removed — the observer
# command group was deleted with the observer machinery.






# PATH-A-TRIM 2026-05-29: test_dashboard_serve_stub removed — the
# dashboard-serve verb + harness.dashboard package were deleted.


