"""Tests for proxy admin verbs (reset-circuit + disable-key)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_state(tmp_path: Path, state: dict) -> None:
    p = tmp_path / ".harness" / "proxy_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state), encoding="utf-8")


def test_reset_circuit_single_key(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {
            "schema_version": 1,
            "started_at": "2026-05-21T00:00:00Z",
            "keys": {
                "k1": {
                    "key_alias": "k1",
                    "circuit_state": "open",
                    "consecutive_failures": 5,
                    "permanent": True,
                }
            },
        })
        result = runner.invoke(cli, ["proxy", "reset-circuit", "k1"])
        assert result.exit_code == 0, result.output
        loaded = json.loads((iso_path / ".harness" / "proxy_state.json").read_text())
        assert loaded["keys"]["k1"]["circuit_state"] == "closed"
        assert loaded["keys"]["k1"]["consecutive_failures"] == 0


def test_disable_key_marks_open_and_permanent(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {
            "schema_version": 1,
            "started_at": "2026-05-21T00:00:00Z",
            "keys": {
                "k1": {
                    "key_alias": "k1",
                    "circuit_state": "closed",
                    "consecutive_failures": 0,
                }
            },
        })
        result = runner.invoke(cli, ["proxy", "disable-key", "k1"])
        assert result.exit_code == 0, result.output
        loaded = json.loads((iso_path / ".harness" / "proxy_state.json").read_text())
        assert loaded["keys"]["k1"]["circuit_state"] == "open"
        assert loaded["keys"]["k1"]["permanent"] is True


def test_reset_circuit_unknown_key(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {
            "schema_version": 1,
            "started_at": "2026-05-21T00:00:00Z",
            "keys": {},
        })
        result = runner.invoke(cli, ["proxy", "reset-circuit", "nope"])
        assert result.exit_code == 1
        assert "Unknown" in result.output


def test_disable_key_unknown(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {
            "schema_version": 1,
            "started_at": "2026-05-21T00:00:00Z",
            "keys": {},
        })
        result = runner.invoke(cli, ["proxy", "disable-key", "nope"])
        assert result.exit_code == 1
        assert "Unknown" in result.output
