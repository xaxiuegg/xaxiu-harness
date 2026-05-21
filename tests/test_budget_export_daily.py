"""Tests for ENGINE-COST-LEDGER-EXPORT."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.budget import export_daily_csv


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _ledger_entries() -> list[dict]:
    return [
        {"timestamp": "2026-05-21T10:00:00Z", "engine": "kimi", "model": "kimi-k2",
         "tokens_in": 100, "tokens_out": 200, "cost_usd": 0.01},
        {"timestamp": "2026-05-21T11:00:00Z", "engine": "kimi", "model": "kimi-k2",
         "tokens_in": 50, "tokens_out": 100, "cost_usd": 0.005},
        {"timestamp": "2026-05-20T10:00:00Z", "engine": "deepseek", "model": "v4-flash",
         "tokens_in": 1000, "tokens_out": 2000, "cost_usd": 0.10},
    ]


def test_export_daily_csv_filters_to_target_date(tmp_path: Path) -> None:
    with patch("harness.budget.read_ledger", return_value=_ledger_entries()):
        out = export_daily_csv(target_dir=tmp_path, date="2026-05-21")
    assert out.exists()
    rows = list(csv.reader(open(out)))
    assert rows[0] == ["date", "engine", "model", "requests",
                       "input_tokens", "output_tokens", "est_usd"]
    # Only kimi/kimi-k2 entries on 2026-05-21
    data_rows = rows[1:]
    assert len(data_rows) == 1
    assert data_rows[0][:3] == ["2026-05-21", "kimi", "kimi-k2"]
    # 2 requests, 150 in, 300 out, $0.015
    assert int(data_rows[0][3]) == 2
    assert int(data_rows[0][4]) == 150
    assert int(data_rows[0][5]) == 300
    assert abs(float(data_rows[0][6]) - 0.015) < 1e-6


def test_export_daily_empty_ledger_writes_header_only(tmp_path: Path) -> None:
    with patch("harness.budget.read_ledger", return_value=[]):
        out = export_daily_csv(target_dir=tmp_path, date="2026-05-21")
    rows = list(csv.reader(open(out)))
    assert len(rows) == 1  # header only


def test_export_daily_aggregates_by_engine_and_model(tmp_path: Path) -> None:
    entries = [
        {"timestamp": "2026-05-21T01:00:00Z", "engine": "kimi", "model": "kimi-k2",
         "tokens_in": 10, "tokens_out": 20, "cost_usd": 0.001},
        {"timestamp": "2026-05-21T02:00:00Z", "engine": "kimi", "model": "kimi-k2",
         "tokens_in": 30, "tokens_out": 40, "cost_usd": 0.003},
        {"timestamp": "2026-05-21T03:00:00Z", "engine": "deepseek", "model": "v4-flash",
         "tokens_in": 100, "tokens_out": 200, "cost_usd": 0.01},
    ]
    with patch("harness.budget.read_ledger", return_value=entries):
        out = export_daily_csv(target_dir=tmp_path, date="2026-05-21")
    data_rows = list(csv.reader(open(out)))[1:]
    assert len(data_rows) == 2  # kimi+kimi-k2 and deepseek+v4-flash
    kimi_row = next(r for r in data_rows if r[1] == "kimi")
    assert int(kimi_row[3]) == 2  # 2 requests


def test_cli_budget_export_daily(runner: CliRunner, tmp_path: Path) -> None:
    with patch("harness.budget.read_ledger", return_value=_ledger_entries()):
        with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
            result = runner.invoke(cli, [
                "budget", "export-daily", "--date", "2026-05-21",
            ])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert "2026-05-21.csv" in result.output
