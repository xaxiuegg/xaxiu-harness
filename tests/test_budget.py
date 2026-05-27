"""Tests for ``src.harness.budget``."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
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
    empty_ledger = tmp_path / "empty.jsonl"
    monkeypatch.setattr("harness.budget.DEFAULT_LEDGER_PATH", empty_ledger)
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", empty_ledger)
    result = runner.invoke(cli, ["budget", "summary"])
    assert result.exit_code == 0
    assert "(no dispatches)" in result.output


def test_budget_show_empty_ledger(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty_ledger = tmp_path / "empty.jsonl"
    monkeypatch.setattr("harness.budget.DEFAULT_LEDGER_PATH", empty_ledger)
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", empty_ledger)
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


# ---------------------------------------------------------------------------
# --since-days tests
# ---------------------------------------------------------------------------


def test_budget_summary_since_days_one(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--since-days 1 should include only entries from the last 24 hours."""
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)
    monkeypatch.setattr("harness.budget.DEFAULT_LEDGER_PATH", ledger)

    # Write two entries directly with controlled timestamps
    fresh = CostEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        task_id="fresh", engine="kimi-api",
        input_tokens=1000, output_tokens=0, latency_ms=0, cost_usd=0.15,
    )
    old = CostEntry(
        timestamp=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        task_id="stale", engine="kimi-api",
        input_tokens=1000, output_tokens=0, latency_ms=0, cost_usd=0.15,
    )
    ledger.write_text(
        fresh.model_dump_json() + "\n" + old.model_dump_json() + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(cli, ["budget", "summary", "--since-days", "1"])
    assert result.exit_code == 0
    assert "kimi-api" in result.output
    # Only the fresh entry is within the 1-day window
    assert "dispatches=1" in result.output


def test_budget_summary_since_days_thirty(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--since-days 30 should include 29-day-old but exclude 31-day-old entries."""
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)
    monkeypatch.setattr("harness.budget.DEFAULT_LEDGER_PATH", ledger)
    
    # Create entries with specific timestamps
    entry_29_days = CostEntry(
        timestamp=(datetime.now(timezone.utc) - timedelta(days=29)).isoformat(),
        task_id="29d",
        engine="kimi-api",
        input_tokens=1000,
        output_tokens=0,
        latency_ms=0,
        cost_usd=0.15,
    )
    entry_31_days = CostEntry(
        timestamp=(datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
        task_id="31d",
        engine="kimi-api",
        input_tokens=1000,
        output_tokens=0,
        latency_ms=0,
        cost_usd=0.15,
    )
    
    ledger.write_text(
        entry_29_days.model_dump_json() + "\n" +
        entry_31_days.model_dump_json() + "\n",
        encoding="utf-8",
    )
    
    result = runner.invoke(cli, ["budget", "summary", "--since-days", "30"])
    assert result.exit_code == 0
    # 29-day entry is within window, 31-day is excluded → dispatches=1
    assert "kimi-api" in result.output
    assert "dispatches=1" in result.output


def test_budget_summary_mutually_exclusive(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both --since and --since-days should exit with usage error."""
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)
    
    result = runner.invoke(cli, ["budget", "summary", "--since", "2024-01-01", "--since-days", "7"])
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_budget_summary_since_days_zero(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--since-days 0 should exit with a usage error (click BadParameter)."""
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)

    result = runner.invoke(cli, ["budget", "summary", "--since-days", "0"])
    assert result.exit_code == 2
    # click renders BadParameter as "Invalid value for '--since-days'"
    assert "--since-days" in result.output
    assert "must be" in result.output


# ---------------------------------------------------------------------------
# WIRE-BUDGET-SWARM (2026-05-22) — D3
# ---------------------------------------------------------------------------

def test_normalize_engine_strips_swarm_prefix() -> None:
    from harness.budget import _normalize_engine
    assert _normalize_engine("swarm/kimi") == "kimi"
    assert _normalize_engine("swarm/kimi-api") == "kimi-api"
    assert _normalize_engine("kimi") == "kimi"


def test_normalize_engine_folds_deepseek_variants() -> None:
    from harness.budget import _normalize_engine
    assert _normalize_engine("swarm/deepseek-v4-flash") == "deepseek"
    assert _normalize_engine("deepseek-v4-flash") == "deepseek"
    assert _normalize_engine("swarm/deepseek-v4-pro") == "deepseek-pro"
    assert _normalize_engine("deepseek-v4-pro-thinking") == "deepseek-pro"


def test_record_dispatch_swarm_kimi_does_not_warn(tmp_path: Path) -> None:
    """swarm/kimi must resolve to the kimi (subscription, zero-cost) row, no warning."""
    ledger = tmp_path / "ledger.jsonl"
    with patch("harness.budget.logger") as mock_logger:
        entry = record_dispatch(
            task_id="t1",
            engine="swarm/kimi",
            input_tokens=1_000_000,
            output_tokens=500_000,
            ledger_path=ledger,
        )
    # kimi is the subscription engine — zero cost — but the WARNING must
    # not fire because the engine is now recognised.
    assert entry.cost_usd == 0.0
    mock_logger.warning.assert_not_called()
    # The raw engine name is preserved in the ledger entry — only the
    # cost lookup is normalised.
    assert entry.engine == "swarm/kimi"


def test_record_dispatch_swarm_deepseek_flash_computes_priced_cost(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    with patch("harness.budget.logger") as mock_logger:
        entry = record_dispatch(
            task_id="t1",
            engine="swarm/deepseek-v4-flash",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            ledger_path=ledger,
        )
    expected = round(0.27 + 1.10, 6)  # deepseek flash rates
    assert entry.cost_usd == expected
    mock_logger.warning.assert_not_called()


def test_record_dispatch_swarm_kimi_api_uses_moonshot_pricing(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    with patch("harness.budget.logger") as mock_logger:
        entry = record_dispatch(
            task_id="t1",
            engine="swarm/kimi-api",
            input_tokens=1_000_000,
            output_tokens=200_000,
            ledger_path=ledger,
        )
    expected = round(0.15 + (0.2 * 2.50), 6)
    assert entry.cost_usd == expected
    mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# P3 audit fix (2026-05-27) — visible unpriced-engine signal
#
# `_compute_cost` previously returned 0.0 for unknown engines with only a
# `logger.warning` (which a non-technical operator never sees).  The
# meter silently undercounted on every model rename.  Now ledger rows
# carry `cost_known=False` and budget/cost-today surface that visibly.
# ---------------------------------------------------------------------------


class TestUnpricedEngineVisibility:
    def test_known_engine_records_cost_known_true(
        self, tmp_path: Path,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        entry = record_dispatch(
            task_id="t1", engine="kimi-api",
            input_tokens=1_000_000, output_tokens=0,
            ledger_path=ledger,
        )
        assert entry.cost_known is True
        # And the priced cost was actually computed
        assert entry.cost_usd > 0.0

    def test_documented_free_engine_records_cost_known_true(
        self, tmp_path: Path,
    ) -> None:
        """mock/mock-engine are KNOWN to be free; not unpriced."""
        ledger = tmp_path / "ledger.jsonl"
        entry = record_dispatch(
            task_id="t1", engine="mock",
            input_tokens=100, output_tokens=50,
            ledger_path=ledger,
        )
        assert entry.cost_known is True
        assert entry.cost_usd == 0.0

    def test_unknown_engine_records_cost_known_false(
        self, tmp_path: Path,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        entry = record_dispatch(
            task_id="t1", engine="future-rename-engine",
            input_tokens=1_000_000, output_tokens=500_000,
            ledger_path=ledger,
        )
        assert entry.cost_known is False
        assert entry.cost_usd == 0.0

    def test_summary_aggregates_unpriced_dispatches(
        self, tmp_path: Path,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="a", engine="kimi-api",
                        input_tokens=1_000_000, ledger_path=ledger)
        record_dispatch(task_id="b", engine="unknown-new",
                        input_tokens=100, ledger_path=ledger)
        record_dispatch(task_id="c", engine="unknown-new",
                        input_tokens=100, ledger_path=ledger)
        agg = summary(ledger)
        # Priced engine: 0 unpriced
        assert agg["kimi-api"]["unpriced_dispatches"] == 0.0
        # Unknown engine: both rows counted as unpriced
        assert agg["unknown-new"]["dispatches"] == 2.0
        assert agg["unknown-new"]["unpriced_dispatches"] == 2.0

    def test_unpriced_engines_since_helper(self, tmp_path: Path) -> None:
        from harness.budget import unpriced_engines_since
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="a", engine="kimi-api",
                        input_tokens=1_000_000, ledger_path=ledger)
        record_dispatch(task_id="b", engine="unknown-1",
                        input_tokens=10, ledger_path=ledger)
        record_dispatch(task_id="c", engine="unknown-2",
                        input_tokens=10, ledger_path=ledger)
        out = unpriced_engines_since(ledger)
        # kimi-api priced, so absent; unknown-1 and unknown-2 both flagged
        assert "kimi-api" not in out
        assert out["unknown-1"] == 1
        assert out["unknown-2"] == 1

    def test_old_ledger_rows_default_to_cost_known_true(
        self, tmp_path: Path,
    ) -> None:
        """Backward-compat: a ledger row written before P3 (no
        ``cost_known`` field) deserializes with the default True
        so historical rows aren't retroactively flagged."""
        ledger = tmp_path / "ledger.jsonl"
        # Hand-write a pre-P3 row (no cost_known field)
        legacy_row = {
            "timestamp": "2026-05-01T00:00:00+00:00",
            "task_id": "old",
            "engine": "deepseek",
            "model": None,
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_ms": 0,
            "cost_usd": 0.001,
        }
        ledger.write_text(json.dumps(legacy_row) + "\n", encoding="utf-8")
        entries = read_ledger(ledger)
        assert len(entries) == 1
        assert entries[0].cost_known is True

    def test_budget_show_tags_unpriced_rows(
        self, runner: CliRunner, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="a", engine="kimi-api",
                        input_tokens=1_000_000, ledger_path=ledger)
        record_dispatch(task_id="b", engine="brand-new-engine",
                        input_tokens=100, ledger_path=ledger)
        monkeypatch.setattr("harness.budget.DEFAULT_LEDGER_PATH", ledger)
        monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)
        result = runner.invoke(cli, ["budget", "show"])
        assert result.exit_code == 0
        # The unpriced row carries the tag
        assert "[UNPRICED]" in result.output
        # And the footer surfaces a visible warning
        assert "UNPRICED" in result.output

    def test_budget_summary_surfaces_unpriced_engine_warning(
        self, runner: CliRunner, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="a", engine="kimi-api",
                        input_tokens=1_000_000, ledger_path=ledger)
        record_dispatch(task_id="b", engine="brand-new-engine",
                        input_tokens=100, ledger_path=ledger)
        monkeypatch.setattr("harness.budget.DEFAULT_LEDGER_PATH", ledger)
        monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)
        # Far-past since so both rows are included
        result = runner.invoke(
            cli, ["budget", "summary", "--since", "2020-01-01"],
        )
        assert result.exit_code == 0
        # Per-engine inline marker
        assert "UNPRICED" in result.output
        # And the footer warning naming the engine
        assert "brand-new-engine" in result.output

    def test_budget_status_sdk_returns_unpriced_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="a", engine="brand-new",
                        input_tokens=100, ledger_path=ledger)
        record_dispatch(task_id="b", engine="kimi-api",
                        input_tokens=1_000_000, ledger_path=ledger)
        import harness
        status = harness.budget_status(
            since_hours=None, ledger_path=ledger,
        )
        assert status["unpriced_dispatches"] == 1

    def test_cost_widget_format_flags_unpriced(
        self, tmp_path: Path,
    ) -> None:
        from harness.cost_widget import format_cost_widget
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="a", engine="brand-new-engine",
                        input_tokens=100, ledger_path=ledger)
        out = format_cost_widget(ledger_path=ledger, since_hours=None)
        assert "UNPRICED" in out
