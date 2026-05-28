"""W14-BUDGET-METER-PER-ENGINE 2026-05-28: tests for the budget-watch
observer hook (Tier 1B of the engine-budget triad)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.budget import (
    CostEntry,
    set_engine_cap,
)
from harness.cli import cli
from harness.observer.budget_watch import (
    check_budget_caps,
    run_budget_watch,
)


@pytest.fixture
def harness_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated working dir with .harness + coord layout."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "coord" / "dev_loop").mkdir(parents=True)
    (tmp_path / "coord" / "observer").mkdir(parents=True)
    return tmp_path


def _seed_spend(
    tmp_path: Path,
    engine: str,
    spend_usd: float,
) -> None:
    """Append a CostEntry with the exact desired spend to the ledger.

    We construct the JSONL row directly so the test can pin a specific
    dollar amount without reverse-engineering the pricing table.
    """
    from datetime import datetime, timezone
    entry = CostEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        task_id="test-seed",
        engine=engine,
        model=engine,
        input_tokens=100,
        output_tokens=50,
        latency_ms=500,
        cost_usd=spend_usd,
    )
    ledger = tmp_path / "coord" / "dev_loop" / "budget_ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")


class TestCheckBudgetCaps:
    def test_no_caps_no_flags(self, harness_dir: Path) -> None:
        """No engine has a cap configured → zero flags."""
        flags = check_budget_caps(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        assert flags == []

    def test_below_threshold_no_flag(self, harness_dir: Path) -> None:
        """Engine with cap + spend below 80% threshold → no flag."""
        set_engine_cap(
            "deepseek", 30.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "deepseek", 5.0)  # 5/30 = 17%
        flags = check_budget_caps(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        assert flags == []

    def test_at_alert_threshold_raises_med_flag(
        self, harness_dir: Path,
    ) -> None:
        """Engine crosses 80% → MED flag."""
        set_engine_cap(
            "deepseek", 30.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "deepseek", 25.0)  # 25/30 = 83.3%
        flags = check_budget_caps(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        assert len(flags) == 1
        assert flags[0].severity == "med"
        assert flags[0].category == "budget_cap_alert"
        assert "deepseek" in flags[0].summary
        assert "83" in flags[0].summary

    def test_over_cap_raises_high_flag(self, harness_dir: Path) -> None:
        """Engine spent more than the cap → HIGH flag."""
        set_engine_cap(
            "mimo", 15.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "mimo", 20.0)  # 20/15 = 133%
        flags = check_budget_caps(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        assert len(flags) == 1
        assert flags[0].severity == "high"
        assert flags[0].category == "budget_cap_exceeded"

    def test_multiple_engines_multiple_flags(self, harness_dir: Path) -> None:
        set_engine_cap(
            "deepseek", 30.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        set_engine_cap(
            "mimo", 15.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "deepseek", 25.0)  # 83% → MED
        _seed_spend(harness_dir, "mimo", 20.0)      # 133% → HIGH
        flags = check_budget_caps(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        assert len(flags) == 2
        severities = {f.severity for f in flags}
        assert severities == {"med", "high"}

    def test_dedup_prevents_duplicate_flags(self, harness_dir: Path) -> None:
        """A given (category, engine, threshold) signature only raises once."""
        set_engine_cap(
            "deepseek", 30.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "deepseek", 25.0)
        # First run raises
        first = run_budget_watch(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        assert len(first) == 1
        # Second run with same state: no new flags (signature already pending)
        second = run_budget_watch(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        assert second == [], (
            "dedup failed: same threshold crossing re-raised"
        )

    def test_skip_dedup_bypass(self, harness_dir: Path) -> None:
        """--skip-dedup re-raises even when signature exists."""
        set_engine_cap(
            "deepseek", 30.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "deepseek", 25.0)
        run_budget_watch(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        flags = check_budget_caps(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
            skip_dedup=True,
        )
        assert len(flags) == 1, "skip_dedup should bypass signature check"


class TestRunBudgetWatchWritesPending:
    def test_med_flag_writes_med_pending_md(self, harness_dir: Path) -> None:
        set_engine_cap(
            "deepseek", 30.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "deepseek", 25.0)
        run_budget_watch(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        med = harness_dir / "coord" / "observer" / "MED_FLAG_PENDING.md"
        assert med.exists()
        content = med.read_text(encoding="utf-8")
        assert "deepseek" in content
        assert "budget_cap_alert" in content

    def test_high_flag_writes_high_pending_md(
        self, harness_dir: Path,
    ) -> None:
        set_engine_cap(
            "mimo", 15.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "mimo", 20.0)
        run_budget_watch(
            observer_dir=harness_dir / "coord" / "observer",
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
            ledger_path=harness_dir / "coord" / "dev_loop" / "budget_ledger.jsonl",
        )
        high = harness_dir / "coord" / "observer" / "HIGH_FLAG_PENDING.md"
        assert high.exists()
        content = high.read_text(encoding="utf-8")
        assert "mimo" in content
        assert "budget_cap_exceeded" in content


class TestBudgetWatchCli:
    def test_help_describes_purpose(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["observer", "budget-watch", "--help"])
        assert result.exit_code == 0
        # Help must mention key behavior
        assert "budget" in result.output.lower()
        assert "cap" in result.output.lower()

    def test_dry_run_no_flags(self, harness_dir: Path) -> None:
        """With no caps configured, dry-run is a clean no-op."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["observer", "budget-watch", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "no new budget flags" in result.output.lower()

    def test_dry_run_with_alert(self, harness_dir: Path) -> None:
        set_engine_cap(
            "deepseek", 30.0,
            cap_path=harness_dir / "coord" / "dev_loop" / "budget_cap.json",
        )
        _seed_spend(harness_dir, "deepseek", 25.0)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["observer", "budget-watch", "--dry-run"],
        )
        assert result.exit_code == 0
        # Output names the engine + alert level
        assert "deepseek" in result.output
        assert "MED" in result.output
