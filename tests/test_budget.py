"""Tests for ``src.harness.budget``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.budget import (
    DEFAULT_CAP_PATH,
    DEFAULT_LEDGER_PATH,
    PRICING_USD_PER_M_TOKENS,
    CostEntry,
    check_cap,
    read_ledger,
    record_dispatch,
    summary,
    total_spent,
)
from harness.cli import cli


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_cost_entry_accepts_valid() -> None:
    entry = CostEntry(
        timestamp="2026-05-21T12:00:00+00:00",
        task_id="t1",
        engine="kimi-api",
        input_tokens=100,
        output_tokens=50,
        latency_ms=200,
        cost_usd=0.65,
    )
    assert entry.task_id == "t1"


def test_cost_entry_rejects_negative_tokens() -> None:
    with pytest.raises(Exception):
        CostEntry(
            timestamp="2026-05-21T12:00:00+00:00",
            task_id="t1",
            engine="kimi-api",
            input_tokens=-1,
            output_tokens=0,
            latency_ms=0,
            cost_usd=0.0,
        )


def test_cost_entry_rejects_negative_cost() -> None:
    with pytest.raises(Exception):
        CostEntry(
            timestamp="2026-05-21T12:00:00+00:00",
            task_id="t1",
            engine="kimi-api",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            cost_usd=-0.01,
        )


# ---------------------------------------------------------------------------
# Pricing math
# ---------------------------------------------------------------------------


def test_record_dispatch_computes_cost_correctly(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    entry = record_dispatch(
        task_id="t1",
        engine="kimi-api",
        input_tokens=1_000_000,
        output_tokens=200_000,
        ledger_path=ledger,
    )
    expected = round(0.15 + 0.50, 6)
    assert entry.cost_usd == expected


def test_record_dispatch_unknown_engine_warns_and_zero_cost(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    with patch("harness.budget.logger") as mock_logger:
        entry = record_dispatch(
            task_id="t1",
            engine="unknown-engine",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            ledger_path=ledger,
        )
    assert entry.cost_usd == 0.0
    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


def test_read_ledger_missing_file_returns_empty(tmp_path: Path) -> None:
    ledger = tmp_path / "nonexistent.jsonl"
    assert read_ledger(ledger) == []


def test_read_ledger_empty_file_returns_empty(tmp_path: Path) -> None:
    ledger = tmp_path / "empty.jsonl"
    ledger.write_text("", encoding="utf-8")
    assert read_ledger(ledger) == []


def test_read_ledger_roundtrip(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    e1 = record_dispatch(task_id="a", engine="kimi", ledger_path=ledger)
    e2 = record_dispatch(task_id="b", engine="deepseek", input_tokens=1_000_000, ledger_path=ledger)
    entries = read_ledger(ledger)
    assert len(entries) == 2
    assert entries[0].task_id == e1.task_id
    assert entries[1].task_id == e2.task_id


# ---------------------------------------------------------------------------
# Summary + since filter
# ---------------------------------------------------------------------------


def test_summary_aggregates_correctly(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    record_dispatch(task_id="a", engine="kimi-api", input_tokens=1_000_000, ledger_path=ledger)
    record_dispatch(task_id="b", engine="kimi-api", output_tokens=200_000, ledger_path=ledger)
    record_dispatch(task_id="c", engine="deepseek", input_tokens=2_000_000, ledger_path=ledger)
    agg = summary(ledger)
    assert agg["kimi-api"]["dispatches"] == 2.0
    assert agg["kimi-api"]["total_cost_usd"] == round(0.15 + 0.50, 6)
    assert agg["deepseek"]["total_cost_usd"] == round(2 * 0.27, 6)


def test_summary_with_since_filter(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    record_dispatch(task_id="old", engine="kimi-api", input_tokens=1_000_000, ledger_path=ledger)
    record_dispatch(task_id="new", engine="kimi-api", input_tokens=1_000_000, ledger_path=ledger)
    entries = read_ledger(ledger)
    since = entries[1].timestamp
    agg = summary(ledger, since_iso=since)
    assert agg["kimi-api"]["dispatches"] == 1.0


def test_total_spent_empty_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    assert total_spent(ledger) == 0.0


def test_summary_this_month_filter_logic(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    record_dispatch(task_id="a", engine="kimi-api", input_tokens=1_000_000, ledger_path=ledger)
    spent = total_spent(ledger)
    assert spent == 0.15


# ---------------------------------------------------------------------------
# Budget cap
# ---------------------------------------------------------------------------


def test_check_cap_no_cap_returns_true(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    within, spent, cap = check_cap(monthly_cap_usd=0.0, ledger_path=ledger)
    assert within is True
    assert spent == 0.0
    assert cap == 0.0


def test_check_cap_over_cap_returns_false(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    record_dispatch(task_id="a", engine="kimi-api", input_tokens=10_000_000, ledger_path=ledger)
    within, spent, cap = check_cap(monthly_cap_usd=1.0, ledger_path=ledger)
    assert within is False
    assert spent >= 1.0


def test_check_cap_reads_cap_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger.jsonl"
    cap_file = tmp_path / "cap.json"
    cap_file.write_text(json.dumps({"monthly_cap_usd": 5.0}), encoding="utf-8")
    monkeypatch.setattr("harness.budget.DEFAULT_CAP_PATH", cap_file)
    within, spent, cap = check_cap(ledger_path=ledger)
    assert cap == 5.0
    assert within is True


# ---------------------------------------------------------------------------
# Atomic write robustness
# ---------------------------------------------------------------------------


def test_atomic_write_failure_keeps_original_intact(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    record_dispatch(task_id="a", engine="kimi", ledger_path=ledger)
    original = ledger.read_bytes()
    with patch("builtins.open", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            record_dispatch(task_id="b", engine="kimi", ledger_path=ledger)
    assert ledger.read_bytes() == original


# ---------------------------------------------------------------------------
# Env pricing override
# ---------------------------------------------------------------------------


def test_env_pricing_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "HARNESS_BUDGET_PRICING_JSON",
        json.dumps({"custom": {"input": 1.0, "output": 2.0}}),
    )
    ledger = tmp_path / "ledger.jsonl"
    entry = record_dispatch(
        task_id="t1", engine="custom", input_tokens=1_000_000, output_tokens=500_000, ledger_path=ledger
    )
    assert entry.cost_usd == round(1.0 + 1.0, 6)


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_budget_help_lists_four_subcommands(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["budget", "--help"])
    assert result.exit_code == 0
    for cmd in ("show", "summary", "set-cap", "reset"):
        assert cmd in result.output


def test_budget_summary_empty_ledger(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("harness.budget.DEFAULT_LEDGER_PATH", tmp_path / "empty.jsonl")
    result = runner.invoke(cli, ["budget", "summary"])
    assert result.exit_code == 0
    assert "(no dispatches)" in result.output


def test_budget_show_empty_ledger(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("harness.budget.DEFAULT_LEDGER_PATH", tmp_path / "empty.jsonl")
    result = runner.invoke(cli, ["budget", "show"])
    assert result.exit_code == 0


def test_budget_set_cap(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cap_file = tmp_path / "cap.json"
    monkeypatch.setattr("harness.cli.DEFAULT_CAP_PATH", cap_file)
    result = runner.invoke(cli, ["budget", "set-cap", "42.50"])
    assert result.exit_code == 0
    data = json.loads(cap_file.read_text(encoding="utf-8"))
    assert data["monthly_cap_usd"] == 42.50


def test_budget_reset_force(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("some old data\n", encoding="utf-8")
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)
    archive_dir = tmp_path / "archive"
    monkeypatch.setattr("harness.cli._budget_archive_dir", lambda: archive_dir)
    result = runner.invoke(cli, ["budget", "reset", "--force"])
    assert result.exit_code == 0
    assert not ledger.exists()


def test_budget_reset_without_force_warns(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("some old data\n", encoding="utf-8")
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)
    result = runner.invoke(cli, ["budget", "reset"])
    assert result.exit_code == 1
    assert "--force" in result.output
