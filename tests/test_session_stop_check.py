"""Tests for the deterministic stop-check gate (anti-premature-stop mechanism)."""

from __future__ import annotations

import csv
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.session.stop_check import (
    _count_queued_production_rows,
    _creativity_recently_fired,
    ok_to_stop,
)


# ---------------------------------------------------------------------------
# _count_queued_production_rows
# ---------------------------------------------------------------------------


def _write_status_csv(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "STATUS.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Category", "Title", "Status", "Owner", "Effort", "Date", "Notes"])
        for r in rows:
            w.writerow([
                r["ID"], r["Category"], r["Title"], r["Status"],
                r.get("Owner", ""), r.get("Effort", ""), r.get("Date", ""),
                r.get("Notes", ""),
            ])
    return p


def test_count_missing_file_returns_zero(tmp_path: Path) -> None:
    assert _count_queued_production_rows(tmp_path / "nope.csv") == 0


def test_count_only_counts_queued_production_categories(tmp_path: Path) -> None:
    p = _write_status_csv(tmp_path, [
        {"ID": "A", "Category": "Production", "Title": "t", "Status": "queued"},
        {"ID": "B", "Category": "Production", "Title": "t", "Status": "shipped"},
        {"ID": "C", "Category": "Refactor", "Title": "t", "Status": "queued"},
        {"ID": "D", "Category": "Operator-UX", "Title": "t", "Status": "queued"},
        {"ID": "E", "Category": "Security", "Title": "t", "Status": "queued"},
        {"ID": "F", "Category": "Process", "Title": "t", "Status": "queued"},
    ])
    assert _count_queued_production_rows(p) == 3  # A + D + E


def test_count_zero_when_all_shipped(tmp_path: Path) -> None:
    p = _write_status_csv(tmp_path, [
        {"ID": "A", "Category": "Production", "Title": "t", "Status": "shipped"},
    ])
    assert _count_queued_production_rows(p) == 0


# ---------------------------------------------------------------------------
# _creativity_recently_fired
# ---------------------------------------------------------------------------


def test_creativity_log_missing_returns_false(tmp_path: Path) -> None:
    # Override BOTH log_path AND status_csv to point at the empty tmp dir
    # so the live STATUS.csv-mtime fallback doesn't fire.
    assert _creativity_recently_fired(
        log_path=tmp_path / "nope.jsonl",
        status_csv=tmp_path / "nope-status.csv",
    ) is False


def test_creativity_log_fresh_returns_true(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    log.write_text("any text\n", encoding="utf-8")
    assert _creativity_recently_fired(
        log_path=log,
        window_seconds=3600,
        status_csv=tmp_path / "nope-status.csv",
    ) is True


def test_creativity_log_old_returns_false(tmp_path: Path) -> None:
    import os
    log = tmp_path / "log.jsonl"
    log.write_text("old\n", encoding="utf-8")
    old = time.time() - 7200  # 2h ago
    os.utime(log, (old, old))
    assert _creativity_recently_fired(
        log_path=log,
        window_seconds=3600,
        status_csv=tmp_path / "nope-status.csv",
    ) is False


def test_creativity_status_csv_fresh_returns_true(tmp_path: Path) -> None:
    """STATUS.csv-mtime fallback fires when log.jsonl is missing/old."""
    status = tmp_path / "STATUS.csv"
    status.write_text("ID,Category\n", encoding="utf-8")
    assert _creativity_recently_fired(
        log_path=tmp_path / "nope.jsonl",
        status_csv=status,
    ) is True


# ---------------------------------------------------------------------------
# ok_to_stop — the main gate
# ---------------------------------------------------------------------------


def test_ok_to_stop_says_no_when_queued_rows_and_no_strongly(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    coord = tmp_path / "coord"
    coord.mkdir()
    _write_status_csv(coord, [
        {"ID": "A", "Category": "Production", "Title": "t", "Status": "queued"},
    ])
    with patch("harness.session.stop_check._session_handoff_recommendation",
               return_value="NONE"):
        ok, reason = ok_to_stop()
    assert ok is False
    assert "queued" in reason.lower()


def test_ok_to_stop_says_yes_when_strongly_recommendation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("harness.session.stop_check._session_handoff_recommendation",
               return_value="STRONGLY"):
        ok, reason = ok_to_stop()
    assert ok is True
    assert "STRONGLY" in reason


def test_ok_to_stop_says_yes_on_operator_flag(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "coord").mkdir()
    (tmp_path / "coord" / "session_stop_approved").write_text("", encoding="utf-8")
    with patch("harness.session.stop_check._session_handoff_recommendation",
               return_value="NONE"):
        ok, reason = ok_to_stop()
    assert ok is True
    assert "operator stop flag" in reason


def test_ok_to_stop_says_no_when_empty_backlog_but_no_creativity(monkeypatch, tmp_path: Path) -> None:
    """0 queued AND no recent activity (STATUS.csv + log both old) ⇒ NOT-YET."""
    import os
    monkeypatch.chdir(tmp_path)
    coord = tmp_path / "coord"
    coord.mkdir()
    _write_status_csv(coord, [
        {"ID": "A", "Category": "Production", "Title": "t", "Status": "shipped"},
    ])
    # Force STATUS.csv mtime far in the past so the freshness fallback
    # does NOT trigger.  This isolates the "no creativity" branch.
    old = time.time() - 7200
    os.utime(coord / "STATUS.csv", (old, old))
    with patch("harness.session.stop_check._session_handoff_recommendation",
               return_value="NONE"):
        ok, reason = ok_to_stop()
    assert ok is False
    assert "creativity" in reason.lower()


def test_ok_to_stop_says_yes_when_empty_backlog_AND_creativity_recent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    coord = tmp_path / "coord"
    (coord / "dev_loop").mkdir(parents=True)
    _write_status_csv(coord, [
        {"ID": "A", "Category": "Production", "Title": "t", "Status": "shipped"},
    ])
    (coord / "dev_loop" / "log.jsonl").write_text("fresh\n", encoding="utf-8")
    with patch("harness.session.stop_check._session_handoff_recommendation",
               return_value="NONE"):
        ok, reason = ok_to_stop()
    assert ok is True
    assert "drained" in reason.lower()


# ---------------------------------------------------------------------------
# CLI verb
# ---------------------------------------------------------------------------


def test_cli_ok_to_stop_exit_0_when_strongly(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    with patch("harness.session.stop_check._session_handoff_recommendation",
               return_value="STRONGLY"):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["session", "ok-to-stop"])
    assert result.exit_code == 0
    assert "ok-to-stop:" in result.output


def test_cli_ok_to_stop_exit_1_when_premature(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        coord = iso_path / "coord"
        coord.mkdir()
        with open(coord / "STATUS.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ID", "Category", "Title", "Status", "Owner", "Effort", "Date", "Notes"])
            w.writerow(["A", "Production", "t", "queued", "", "", "", ""])
        with patch("harness.session.stop_check._session_handoff_recommendation",
                   return_value="NONE"):
            result = runner.invoke(cli, ["session", "ok-to-stop"])
    assert result.exit_code == 1
    assert "NOT-YET:" in result.output
