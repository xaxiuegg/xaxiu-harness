"""W5-S — engine-agnostic memory store + worker prompt integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.memory import (
    MemoryEntry, find_by_name, format_for_packet, load_all, memory_dir, search,
)


# ---------------------------------------------------------------------------
# load_all
# ---------------------------------------------------------------------------

def test_load_all_missing_dir(tmp_path: Path) -> None:
    """No memory/ dir → empty list, no crash."""
    assert load_all(tmp_path) == []


def test_load_all_basic(tmp_path: Path) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "alpha.md").write_text("# Alpha\n\nFirst entry\n", encoding="utf-8")
    (mdir / "beta.md").write_text("# Beta\n\nSecond entry\n", encoding="utf-8")
    entries = load_all(tmp_path)
    assert len(entries) == 2
    assert entries[0].name == "alpha"
    assert entries[0].title == "Alpha"
    assert entries[1].name == "beta"


def test_load_all_uses_filename_when_no_h1(tmp_path: Path) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "no-heading.md").write_text("just content, no h1\n", encoding="utf-8")
    entries = load_all(tmp_path)
    assert len(entries) == 1
    assert entries[0].title == "no-heading"


def test_load_all_skips_unreadable(tmp_path: Path) -> None:
    """Malformed encoding or unreadable file is skipped, doesn't crash."""
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "good.md").write_text("# Good\n", encoding="utf-8")
    (mdir / "bad.md").write_bytes(b"\xff\xfe\x00\x00malformed-utf-8")
    entries = load_all(tmp_path)
    # Good entry survives, bad is skipped
    names = [e.name for e in entries]
    assert "good" in names


def test_load_all_ignores_non_md(tmp_path: Path) -> None:
    """Only .md files are picked up."""
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "real.md").write_text("# Real\n", encoding="utf-8")
    (mdir / "notes.txt").write_text("not markdown\n", encoding="utf-8")
    entries = load_all(tmp_path)
    assert len(entries) == 1
    assert entries[0].name == "real"


# ---------------------------------------------------------------------------
# find_by_name
# ---------------------------------------------------------------------------

def test_find_by_name_present(tmp_path: Path) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    e = find_by_name("alpha", tmp_path)
    assert e is not None
    assert e.name == "alpha"


def test_find_by_name_missing(tmp_path: Path) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    assert find_by_name("nonexistent", tmp_path) is None


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def test_search_matches_name_title_content(tmp_path: Path) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "engines.md").write_text("# Engines\n\nDeepSeek and MiMo\n",
                                      encoding="utf-8")
    (mdir / "convention.md").write_text("# Convention\n\ngit commits\n",
                                         encoding="utf-8")
    # Content match
    matches = search("deepseek", tmp_path)
    assert len(matches) == 1
    assert matches[0].name == "engines"
    # Title match
    matches = search("Convention", tmp_path)
    assert len(matches) == 1
    # Multiple match
    matches = search("e", tmp_path)
    assert len(matches) == 2


def test_search_empty_query(tmp_path: Path) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "x.md").write_text("# X\n", encoding="utf-8")
    assert search("", tmp_path) == []
    assert search("   ", tmp_path) == []


def test_search_case_insensitive(tmp_path: Path) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "x.md").write_text("# X\n\nFooBarBaz\n", encoding="utf-8")
    assert len(search("foobar", tmp_path)) == 1


# ---------------------------------------------------------------------------
# format_for_packet
# ---------------------------------------------------------------------------

def test_format_for_packet_empty_when_no_memory(tmp_path: Path) -> None:
    assert format_for_packet(repo_root=tmp_path) == ""


def test_format_for_packet_includes_all(tmp_path: Path) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "a.md").write_text("# A\n\ncontent-a\n", encoding="utf-8")
    (mdir / "b.md").write_text("# B\n\ncontent-b\n", encoding="utf-8")
    out = format_for_packet(repo_root=tmp_path)
    assert "memory/a.md" in out
    assert "memory/b.md" in out
    assert "content-a" in out
    assert "content-b" in out
    assert "Operator-curated memory" in out


def test_format_for_packet_truncates_at_size(tmp_path: Path) -> None:
    """Large memory should truncate with notice; small memory inlines."""
    mdir = tmp_path / "memory"
    mdir.mkdir()
    big_content = "x" * 10000
    (mdir / "huge.md").write_text(f"# Huge\n\n{big_content}\n", encoding="utf-8")
    (mdir / "tiny.md").write_text("# Tiny\n\nfits\n", encoding="utf-8")
    # Force tight cap
    out = format_for_packet(repo_root=tmp_path, max_total_bytes=500)
    assert "truncated" in out.lower()


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_cli_memory_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "test-entry.md").write_text("# Test Entry\n\nbody\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "list"])
    assert result.exit_code == 0
    assert "test-entry" in result.output
    assert "Test Entry" in result.output


def test_cli_memory_show_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "show", "nonexistent"])
    assert result.exit_code == 1


def test_cli_memory_search_no_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mdir = tmp_path / "memory"
    mdir.mkdir()
    (mdir / "x.md").write_text("# X\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "search", "zzz-no-match"])
    assert result.exit_code == 0
    assert "no memory entries match" in result.output.lower()


def test_cli_memory_help_exposed() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "show" in result.output
    assert "search" in result.output
