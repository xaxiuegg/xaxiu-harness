"""W10-STATUS-CSV-OVERWHELM: regression tests for `harness status list --recent N`.

296-row STATUS.csv is impossible for a non-technical operator to scan.
--recent N shows only the N most recently updated rows + a footer
naming how many older rows remain in the file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness import cli as _cli


_FIXTURE_CSV = """\
ID,Category,Title,Status,Owner,Effort,Updated,Notes
ROW-001,Production,Old row 1,shipped,Claude,-,2026-01-01,old
ROW-002,Production,Old row 2,shipped,Claude,-,2026-02-01,old
ROW-003,Process,Mid row,shipped,Claude,-,2026-03-01,mid
ROW-004,Production,Recent row 1,shipped,Claude,-,2026-05-20,recent
ROW-005,Production,Recent row 2,shipped,Claude,-,2026-05-22,recent
ROW-006,Process,Recent row 3,todo,Claude,-,2026-05-24,recent
ROW-007,Production,Most recent,shipped,Claude,-,2026-05-25,latest
"""


@pytest.fixture
def status_csv(tmp_path):
    p = tmp_path / "STATUS.csv"
    p.write_text(_FIXTURE_CSV, encoding="utf-8")
    return p


def test_status_list_without_recent_shows_all(status_csv, monkeypatch):
    monkeypatch.setattr(_cli, "_status_csv_path", lambda: status_csv)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["status", "list"])
    assert result.exit_code == 0
    # All 7 rows visible
    for rid in ("ROW-001", "ROW-002", "ROW-003", "ROW-004",
                "ROW-005", "ROW-006", "ROW-007"):
        assert rid in result.output
    # No truncation footer
    assert "older row" not in result.output


def test_status_list_recent_3_shows_only_top_3_by_updated(status_csv, monkeypatch):
    monkeypatch.setattr(_cli, "_status_csv_path", lambda: status_csv)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["status", "list", "--recent", "3"])
    assert result.exit_code == 0
    # Newest 3 by Updated date: ROW-007 (05-25), ROW-006 (05-24), ROW-005 (05-22)
    assert "ROW-007" in result.output
    assert "ROW-006" in result.output
    assert "ROW-005" in result.output
    # Older 4 should NOT be in output
    for rid in ("ROW-001", "ROW-002", "ROW-003", "ROW-004"):
        assert rid not in result.output
    # Truncation footer present
    assert "4 older row" in result.output


def test_status_list_recent_larger_than_total_shows_all_no_footer(
    status_csv, monkeypatch
):
    monkeypatch.setattr(_cli, "_status_csv_path", lambda: status_csv)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["status", "list", "--recent", "20"])
    assert result.exit_code == 0
    # All 7 visible (since 20 > 7)
    for rid in ("ROW-001", "ROW-007"):
        assert rid in result.output
    assert "older row" not in result.output


def test_status_list_recent_zero_truncates_to_zero(status_csv, monkeypatch):
    monkeypatch.setattr(_cli, "_status_csv_path", lambda: status_csv)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["status", "list", "--recent", "0"])
    assert result.exit_code == 0
    # No row IDs in output
    for rid in ("ROW-001", "ROW-007"):
        assert rid not in result.output
    assert "7 older row" in result.output


def test_status_list_recent_combines_with_filter(status_csv, monkeypatch):
    """--filter applies first, then --recent on the filtered set."""
    monkeypatch.setattr(_cli, "_status_csv_path", lambda: status_csv)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, [
        "status", "list", "--filter", "shipped", "--recent", "2",
    ])
    assert result.exit_code == 0
    # 6 rows are shipped (all except ROW-006 which is todo); top 2 by
    # date among shipped: ROW-007 (05-25), ROW-005 (05-22)
    assert "ROW-007" in result.output
    assert "ROW-005" in result.output
    assert "ROW-006" not in result.output  # todo, filtered out
    # 4 older shipped rows truncated
    assert "4 older row" in result.output


def test_status_list_json_format_ignores_recent_for_ci_safety(
    status_csv, monkeypatch
):
    """CI consumers depend on JSON dumps; --recent should NOT truncate JSON."""
    monkeypatch.setattr(_cli, "_status_csv_path", lambda: status_csv)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, [
        "status", "list", "--recent", "3", "--format", "json",
    ])
    assert result.exit_code == 0
    # All 7 rows should appear in the JSON
    for rid in ("ROW-001", "ROW-002", "ROW-007"):
        assert rid in result.output


def test_status_list_csv_format_ignores_recent_for_ci_safety(
    status_csv, monkeypatch
):
    """CSV format same — full set for downstream tooling."""
    monkeypatch.setattr(_cli, "_status_csv_path", lambda: status_csv)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, [
        "status", "list", "--recent", "2", "--format", "csv",
    ])
    assert result.exit_code == 0
    for rid in ("ROW-001", "ROW-007"):
        assert rid in result.output
