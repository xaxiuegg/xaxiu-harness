"""Tests for PROXY-RESET-DOCS — unquarantine verb."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.proxy.cli import unquarantine
from harness.proxy.state import CircuitState, KeyState, ProxyState


def _make_state(keys: dict[str, dict]) -> ProxyState:
    return ProxyState(
        schema_version=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        keys={
            alias: KeyState(
                key_alias=alias,
                permanent=info.get("permanent", False),
                auto_quarantined_at=info.get("auto_quarantined_at"),
                consecutive_failures=info.get("failures", 0),
                circuit_state=info.get("circuit", CircuitState.CLOSED),
            )
            for alias, info in keys.items()
        },
    )


def test_unquarantine_requires_alias_or_all() -> None:
    with patch("harness.proxy.cli.read_state",
               return_value=_make_state({"k1": {"permanent": True}})), \
         patch("harness.proxy.cli.write_state") as _:
        ok, msg = unquarantine()
    assert ok is False
    assert "--alias" in msg or "--all" in msg


def test_unquarantine_clears_specific_key() -> None:
    state = _make_state({
        "k1": {"permanent": True, "auto_quarantined_at": "2026-05-21T01:00:00Z",
               "failures": 5, "circuit": CircuitState.OPEN},
        "k2": {"permanent": False},
    })
    with patch("harness.proxy.cli.read_state", return_value=state), \
         patch("harness.proxy.cli.write_state") as mock_w:
        ok, msg = unquarantine(alias="k1")
    assert ok is True
    assert "k1" in msg
    # k1 cleared; k2 untouched
    assert state.keys["k1"].permanent is False
    assert state.keys["k1"].auto_quarantined_at is None
    assert state.keys["k1"].circuit_state == CircuitState.CLOSED
    assert state.keys["k1"].consecutive_failures == 0


def test_unquarantine_all_clears_every_key() -> None:
    state = _make_state({
        "k1": {"permanent": True},
        "k2": {"permanent": True, "auto_quarantined_at": "x"},
        "k3": {"permanent": False},
    })
    with patch("harness.proxy.cli.read_state", return_value=state), \
         patch("harness.proxy.cli.write_state"):
        ok, msg = unquarantine(all_keys=True)
    assert ok is True
    assert "k1" in msg and "k2" in msg
    # k3 wasn't quarantined so not included
    assert "k3" not in msg


def test_unquarantine_no_matches_returns_false() -> None:
    state = _make_state({"k1": {"permanent": False}})
    with patch("harness.proxy.cli.read_state", return_value=state), \
         patch("harness.proxy.cli.write_state"):
        ok, msg = unquarantine(all_keys=True)
    assert ok is False
    assert "no quarantined" in msg.lower()


def test_cli_unquarantine_alias_arg() -> None:
    runner = CliRunner()
    with patch("harness.proxy.cli.unquarantine",
               return_value=(True, "unquarantined: k1")):
        result = runner.invoke(cli, ["proxy", "unquarantine", "--alias", "k1"])
    assert result.exit_code == 0
    assert "unquarantined: k1" in result.output


def test_cli_unquarantine_no_match_exits_1() -> None:
    runner = CliRunner()
    with patch("harness.proxy.cli.unquarantine",
               return_value=(False, "no quarantined keys matched")):
        result = runner.invoke(cli, ["proxy", "unquarantine", "--all"])
    assert result.exit_code == 1
