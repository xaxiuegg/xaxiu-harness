"""Tests for `harness engines-heal` — W8-ENGINES-HEAL."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli


def test_engines_heal_all_healthy_exits_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No dead, no quarantined → 'All engines healthy' + exit 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.engine_alarm.dead_engines", lambda: {})
    monkeypatch.setattr("harness.state.files.read_engine_health",
                        lambda: {})
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-heal"])
    assert result.exit_code == 0
    assert "All engines are healthy" in result.output


def test_engines_heal_quarantines_dead_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead engine (above failure threshold) gets quarantined."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.engine_alarm.dead_engines",
                        lambda: {"kimi": 7})
    monkeypatch.setattr("harness.state.files.read_engine_health",
                        lambda: {"kimi": {"status": "ok"}})
    monkeypatch.setattr("harness.secrets.dpapi.has_secret",
                        lambda *args: True)
    update_calls: list = []
    monkeypatch.setattr(
        "harness.state.files.update_engine_health",
        lambda name, fields: update_calls.append((name, fields)),
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-heal"])
    assert result.exit_code == 0
    assert "kimi" in result.output
    assert "quarantined" in result.output.lower()
    assert "7 consecutive failures" in result.output
    assert len(update_calls) == 1
    assert update_calls[0][0] == "kimi"
    assert update_calls[0][1]["status"] == "quarantined"


def test_engines_heal_dry_run_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--dry-run never invokes update_engine_health."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.engine_alarm.dead_engines",
                        lambda: {"deepseek": 5})
    monkeypatch.setattr("harness.state.files.read_engine_health",
                        lambda: {"deepseek": {"status": "ok"}})
    monkeypatch.setattr("harness.secrets.dpapi.has_secret",
                        lambda *args: True)
    update_calls: list = []
    monkeypatch.setattr(
        "harness.state.files.update_engine_health",
        lambda name, fields: update_calls.append((name, fields)),
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-heal", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "would-quarantine" in result.output
    assert update_calls == []


def test_engines_heal_recovers_quarantined_with_key_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engine is already quarantined AND key is in DPAPI → mark
    recovering so the dispatcher gives it one more attempt."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.engine_alarm.dead_engines", lambda: {})
    monkeypatch.setattr(
        "harness.state.files.read_engine_health",
        lambda: {"mimo": {"status": "quarantined"}}
    )
    monkeypatch.setattr("harness.secrets.dpapi.has_secret",
                        lambda *args: True)
    update_calls: list = []
    monkeypatch.setattr(
        "harness.state.files.update_engine_health",
        lambda name, fields: update_calls.append((name, fields)),
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-heal"])
    assert result.exit_code == 0
    assert "mimo" in result.output
    assert "recovering" in result.output.lower()
    assert len(update_calls) == 1
    assert update_calls[0][1]["status"] == "recovering"


def test_engines_heal_blocked_when_no_key_in_dpapi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quarantined + no key → blocked; operator must seed key first."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.engine_alarm.dead_engines", lambda: {})
    monkeypatch.setattr(
        "harness.state.files.read_engine_health",
        lambda: {"anthropic": {"status": "quarantined"}}
    )
    monkeypatch.setattr("harness.secrets.dpapi.has_secret",
                        lambda *args: False)
    update_calls: list = []
    monkeypatch.setattr(
        "harness.state.files.update_engine_health",
        lambda name, fields: update_calls.append((name, fields)),
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-heal"])
    assert result.exit_code == 0
    assert "anthropic" in result.output
    assert "[X]" in result.output  # blocked glyph
    assert "no API key" in result.output or "fresh key" in result.output
    # Did NOT write engine_health — engine stays quarantined
    assert update_calls == []


def test_engines_heal_with_engine_flag_targets_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--engine flag filters to one engine; ignores others."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "harness.engine_alarm.dead_engines",
        lambda: {"kimi": 7, "anthropic": 5},
    )
    monkeypatch.setattr("harness.state.files.read_engine_health",
                        lambda: {"kimi": {"status": "ok"},
                                 "anthropic": {"status": "ok"}})
    monkeypatch.setattr("harness.secrets.dpapi.has_secret",
                        lambda *args: True)
    update_calls: list = []
    monkeypatch.setattr(
        "harness.state.files.update_engine_health",
        lambda name, fields: update_calls.append((name, fields)),
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-heal", "--engine", "kimi"])
    assert result.exit_code == 0
    assert "kimi" in result.output
    assert "anthropic" not in result.output
    assert len(update_calls) == 1
    assert update_calls[0][0] == "kimi"


def test_engines_heal_with_unknown_engine_exits_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--engine for a healthy engine → 'not in the dead set' + exit 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.engine_alarm.dead_engines", lambda: {})
    monkeypatch.setattr("harness.state.files.read_engine_health",
                        lambda: {})
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-heal", "--engine", "kimi"])
    assert result.exit_code == 0
    assert "not in the dead" in result.output


def test_engines_heal_includes_reversal_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Applied actions surface the operator-facing undo command."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.engine_alarm.dead_engines",
                        lambda: {"deepseek": 6})
    monkeypatch.setattr("harness.state.files.read_engine_health",
                        lambda: {"deepseek": {"status": "ok"}})
    monkeypatch.setattr("harness.secrets.dpapi.has_secret",
                        lambda *args: True)
    monkeypatch.setattr(
        "harness.state.files.update_engine_health",
        lambda name, fields: None,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-heal"])
    assert result.exit_code == 0
    # Reversal instructions for the operator
    assert "harness engines reset" in result.output
