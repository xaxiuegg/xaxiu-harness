"""W4-H: UX polish surfaced by W4-G multi-agent campaign.

The campaign caught 3 cases where external agents (Kimi/MiMo/DeepSeek)
read the harness source and guessed plausible invocations that didn't
actually work.  Each is a real UX papercut — fixing them makes the
harness behave the way external readers expect.

1. ``harness engines list`` (agent guess) ↔ ``harness engines --list`` (orig)
2. ``harness lint-spec --spec X.md`` (guess) ↔ ``lint-spec X.md`` (orig)
3. ``read_status()`` (guess, zero-arg) ↔ ``read_status(path)`` (orig)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.status.store import read_status, write_status
from harness.status.schema import StatusRow, Status


# ---------------------------------------------------------------------------
# Fix 1: harness engines list subcommand
# ---------------------------------------------------------------------------

def test_engines_list_subcommand_works() -> None:
    """`harness engines list` should be equivalent to `harness engines --list`."""
    runner = CliRunner()
    flag_result = runner.invoke(cli, ["engines", "--list"])
    subcmd_result = runner.invoke(cli, ["engines", "list"])
    assert flag_result.exit_code == 0
    assert subcmd_result.exit_code == 0
    # Both should mention at least one of our known engines
    assert "deepseek" in flag_result.output
    assert "deepseek" in subcmd_result.output


def test_engines_unknown_subcommand_errors() -> None:
    """`harness engines foobar` should reject unknown subcommands cleanly."""
    runner = CliRunner()
    result = runner.invoke(cli, ["engines", "foobar"])
    assert result.exit_code == 2
    # CliRunner mixes stderr into result.output for unhandled exit codes
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "unknown subcommand" in combined.lower()


def test_engines_no_arg_defaults_to_list() -> None:
    """`harness engines` (no flag, no subcommand) should default to listing."""
    runner = CliRunner()
    result = runner.invoke(cli, ["engines"])
    assert result.exit_code == 0
    assert "deepseek" in result.output


# ---------------------------------------------------------------------------
# Fix 2: harness lint-spec --spec flag (alongside positional)
# ---------------------------------------------------------------------------









# ---------------------------------------------------------------------------
# Fix 3: read_status() with default path
# ---------------------------------------------------------------------------

def test_read_status_default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`read_status()` with no arg should resolve to coord/STATUS.csv."""
    # Create a fake coord/STATUS.csv in tmp_path, then cd there
    coord = tmp_path / "coord"
    coord.mkdir()
    status_path = coord / "STATUS.csv"
    write_status(
        status_path,
        [StatusRow(
            id="TEST-1", category="Test", title="default-path read",
            status=Status.SHIPPED, owner="test", effort="0", updated="2026-05-22",
            notes="",
        )],
    )
    monkeypatch.chdir(tmp_path)
    rows = read_status()  # no arg
    assert len(rows) == 1
    assert rows[0].id == "TEST-1"


def test_read_status_default_path_missing_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If coord/STATUS.csv is missing under cwd, return empty list, not crash."""
    monkeypatch.chdir(tmp_path)  # no coord/STATUS.csv here
    rows = read_status()
    assert rows == []


def test_read_status_explicit_path_still_works(tmp_path: Path) -> None:
    """Original signature with explicit path must still work."""
    path = tmp_path / "explicit.csv"
    write_status(
        path,
        [StatusRow(
            id="EXP-1", category="Test", title="explicit-path read",
            status=Status.SHIPPED, owner="test", effort="0", updated="2026-05-22",
            notes="",
        )],
    )
    rows = read_status(path)
    assert len(rows) == 1
    assert rows[0].id == "EXP-1"
