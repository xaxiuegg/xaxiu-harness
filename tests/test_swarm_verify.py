"""Tests for SWARM-LANDING-VERIFY."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.swarm_verify import (
    LandingResult, summarize, verify_landings, _latest_swarm_run,
)


def test_latest_swarm_run_returns_none_when_root_missing(tmp_path: Path) -> None:
    assert _latest_swarm_run(tmp_path / "nope") is None


def test_latest_swarm_run_returns_newest(tmp_path: Path) -> None:
    (tmp_path / "20260520T000000-aaaa").mkdir(parents=True)
    (tmp_path / "20260521T000000-bbbb").mkdir(parents=True)
    out = _latest_swarm_run(tmp_path)
    assert out.name == "20260521T000000-bbbb"


def test_verify_landings_empty_expected_returns_empty() -> None:
    assert verify_landings([]) == []


def test_verify_landings_reports_mutated(tmp_path: Path) -> None:
    """When git diff includes the expected path, status=mutated."""
    with patch("harness.swarm_verify._git_diff_files", return_value={"src/x.py"}), \
         patch("harness.swarm_verify._untracked_files", return_value=set()), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        results = verify_landings(["src/x.py"])
    assert len(results) == 1
    assert results[0].status == "mutated"


def test_verify_landings_reports_unmutated(tmp_path: Path) -> None:
    with patch("harness.swarm_verify._git_diff_files", return_value=set()), \
         patch("harness.swarm_verify._untracked_files", return_value=set()), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        results = verify_landings(["src/y.py"])
    assert results[0].status == "unmutated"


def test_verify_landings_includes_untracked_as_mutated(tmp_path: Path) -> None:
    """A new file shows up in untracked, not git-diff."""
    with patch("harness.swarm_verify._git_diff_files", return_value=set()), \
         patch("harness.swarm_verify._untracked_files", return_value={"src/new.py"}), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        results = verify_landings(["src/new.py"])
    assert results[0].status == "mutated"


def test_summarize_counts_each_bucket() -> None:
    rs = [
        LandingResult("a", "mutated"),
        LandingResult("b", "mutated"),
        LandingResult("c", "unmutated"),
    ]
    s = summarize(rs)
    assert s["mutated"] == 2
    assert s["unmutated"] == 1


def test_cli_swarm_verify_all_landed(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    with patch("harness.swarm_verify._git_diff_files", return_value={"src/x.py"}), \
         patch("harness.swarm_verify._untracked_files", return_value=set()), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        result = runner.invoke(cli, [
            "swarm-verify", "--expect-edits-in", "src/x.py",
        ])
    assert result.exit_code == 0
    assert "all_landed=True" in result.output


def test_cli_swarm_verify_missing_path_exits_1(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    with patch("harness.swarm_verify._git_diff_files", return_value=set()), \
         patch("harness.swarm_verify._untracked_files", return_value=set()), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        result = runner.invoke(cli, [
            "swarm-verify", "--expect-edits-in", "src/missing.py",
        ])
    assert result.exit_code == 1
