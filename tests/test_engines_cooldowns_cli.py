"""Tests for `harness engines cooldowns` (or engines-cooldowns)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_no_active_cooldowns(runner: CliRunner, tmp_path: Path) -> None:
    """Prints 'no active cooldowns' when state has none."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        # No state.json → read_state returns defaults (no cooldowns)
        result = runner.invoke(cli, ["engines", "cooldowns"])  # or ["engines-cooldowns"]
        # If subcommand layout, this works; if separate command, try the other:
        if result.exit_code != 0:
            result = runner.invoke(cli, ["engines-cooldowns"])
    assert result.exit_code == 0
    assert "no active cooldowns" in result.output


def test_shows_cooldown_entries(runner: CliRunner, tmp_path: Path) -> None:
    """Lists each engine with its until + reason."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        state_path = iso_path / "coord" / "dev_loop" / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "schema_version": 1,
            "loop_status": "armed",
            "tick_count": 0,
            "phase_status": {},
            "engine_cooldowns": {
                "swarm/kimi": {"until": "2099-01-01T00:00:00Z", "reason": "timeout"},
                "swarm/deepseek": {"until": "2099-01-02T00:00:00Z", "reason": "rate_limit"},
            },
        }), encoding="utf-8")
        result = runner.invoke(cli, ["engines", "cooldowns"])
        if result.exit_code != 0:
            result = runner.invoke(cli, ["engines-cooldowns"])
    assert result.exit_code == 0, result.output
    assert "swarm/kimi" in result.output
    assert "swarm/deepseek" in result.output
    assert "timeout" in result.output


def test_handles_string_cooldown_value(runner: CliRunner, tmp_path: Path) -> None:
    """Bare-string cooldown (legacy shape) still prints."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        state_path = iso_path / "coord" / "dev_loop" / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "schema_version": 1,
            "loop_status": "armed",
            "tick_count": 0,
            "phase_status": {},
            "engine_cooldowns": {"swarm/kimi": "2099-01-01T00:00:00Z"},
        }), encoding="utf-8")
        result = runner.invoke(cli, ["engines", "cooldowns"])
        if result.exit_code != 0:
            result = runner.invoke(cli, ["engines-cooldowns"])
    assert result.exit_code == 0
    assert "swarm/kimi" in result.output
