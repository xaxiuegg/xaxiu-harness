"""W10-PROFILE-AWARE-DEFAULTS: tests for harness.operator.saved_profile +
the `harness profile set/show` CLI subcommands.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness import cli as _cli
from harness.operator import saved_profile as sp


# -- save_profile / load_profile -----------------------------------------


def test_save_profile_writes_atomic(tmp_path):
    target = tmp_path / "profile.json"
    record = sp.save_profile("non_technical", path=target)
    assert record.profile == "non_technical"
    assert record.schema_version == 1
    # File exists + content valid
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["profile"] == "non_technical"
    assert data["schema_version"] == 1
    assert "updated_at" in data


def test_save_profile_rejects_unknown(tmp_path):
    target = tmp_path / "profile.json"
    with pytest.raises(ValueError, match="unknown profile"):
        sp.save_profile("expert", path=target)
    # File NOT created on failure
    assert not target.exists()


def test_save_profile_overwrites_atomically(tmp_path):
    target = tmp_path / "profile.json"
    sp.save_profile("technical", path=target)
    sp.save_profile("non_technical", path=target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["profile"] == "non_technical"
    # No .tmp leftover (atomic helper cleaned up)
    assert list(tmp_path.glob("*.tmp")) == []


def test_load_profile_returns_none_when_missing(tmp_path):
    assert sp.load_profile(path=tmp_path / "no-such.json") is None


def test_load_profile_returns_none_on_invalid_json(tmp_path):
    target = tmp_path / "profile.json"
    target.write_text("not json{", encoding="utf-8")
    assert sp.load_profile(path=target) is None


def test_load_profile_returns_none_on_unknown_profile_value(tmp_path):
    target = tmp_path / "profile.json"
    target.write_text(
        json.dumps({"schema_version": 1, "profile": "alien",
                    "updated_at": "2026-05-25"}),
        encoding="utf-8",
    )
    assert sp.load_profile(path=target) is None


def test_load_profile_returns_record_on_valid_file(tmp_path):
    target = tmp_path / "profile.json"
    sp.save_profile("technical", path=target)
    loaded = sp.load_profile(path=target)
    assert loaded is not None
    assert loaded.profile == "technical"


# -- resolve_profile precedence -----------------------------------------


def test_resolve_profile_cli_flag_wins(tmp_path):
    target = tmp_path / "profile.json"
    sp.save_profile("non_technical", path=target)
    # CLI flag overrides saved
    assert sp.resolve_profile("technical", path=target) == "technical"


def test_resolve_profile_falls_back_to_saved(tmp_path):
    target = tmp_path / "profile.json"
    sp.save_profile("non_technical", path=target)
    assert sp.resolve_profile(None, path=target) == "non_technical"


def test_resolve_profile_returns_none_when_unset(tmp_path):
    """Neither CLI flag nor saved -> None so caller uses built-in default."""
    assert sp.resolve_profile(None, path=tmp_path / "missing.json") is None


# -- CLI: harness profile set ---------------------------------------------


def test_cli_profile_set_writes_file(tmp_path, monkeypatch):
    target = tmp_path / "profile.json"
    monkeypatch.setattr(sp, "default_profile_path", lambda: target)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["profile", "set", "non_technical"])
    assert result.exit_code == 0
    assert "saved profile=non_technical" in result.output
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["profile"] == "non_technical"


def test_cli_profile_set_rejects_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "default_profile_path", lambda: tmp_path / "p.json")
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["profile", "set", "expert"])
    # Click's Choice constraint rejects before our code runs
    assert result.exit_code != 0
    assert "expert" in result.output.lower() or "invalid" in result.output.lower()


# -- CLI: harness profile show -------------------------------------------


def test_cli_profile_show_when_set(tmp_path, monkeypatch):
    target = tmp_path / "profile.json"
    monkeypatch.setattr(sp, "default_profile_path", lambda: target)
    sp.save_profile("technical", path=target)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["profile", "show"])
    assert result.exit_code == 0
    assert "technical" in result.output
    assert str(target) in result.output


def test_cli_profile_show_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "default_profile_path",
                        lambda: tmp_path / "no-such.json")
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["profile", "show"])
    assert result.exit_code == 1
    assert "no saved profile" in result.output.lower()
    # Operator gets the recipe to fix
    assert "harness profile set" in result.output
