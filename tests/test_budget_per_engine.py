"""W14-BUDGET-METER-PER-ENGINE: tests for per-engine caps + enforcement.

Coverage:
  - read_caps_config / write_caps_config round-trip
  - read_caps_config backward-compat with v1 single-cap schema
  - set_engine_cap (add, update, remove via 0)
  - _spent_this_month_by_engine canonicalization
    (swarm/kimi → kimi, deepseek-v4-flash → deepseek, mimo-pro-sub → mimo)
  - check_engine_cap (within / over / alert / no-cap / unconfigured engine)
  - enforce_engine_cap raises CapExceededError when over
  - all_engines_status sorts + dedupes
  - CLI verbs: budget caps (pretty + json), budget set-engine-cap
  - Old check_cap still works with both schema versions
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.budget import (
    CapExceededError,
    DEFAULT_ALERT_THRESHOLD_PCT,
    EngineCapStatus,
    all_engines_status,
    check_cap,
    check_engine_cap,
    enforce_engine_cap,
    read_caps_config,
    record_dispatch,
    set_engine_cap,
    write_caps_config,
    _spent_this_month_by_engine,
)
from harness.cli import cli


# ---------------------------------------------------------------------------
# read_caps_config / write_caps_config
# ---------------------------------------------------------------------------


class TestReadCapsConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        config = read_caps_config(cap_path=path)
        assert config["monthly_cap_usd"] == 0.0
        assert config["per_engine_caps_usd"] == {}
        assert config["alert_threshold_pct"] == DEFAULT_ALERT_THRESHOLD_PCT

    def test_v1_schema_backward_compat(self, tmp_path: Path) -> None:
        """Old single-cap JSON files still read correctly."""
        path = tmp_path / "v1.json"
        path.write_text(json.dumps({"monthly_cap_usd": 42.5}),
                        encoding="utf-8")
        config = read_caps_config(cap_path=path)
        assert config["monthly_cap_usd"] == 42.5
        assert config["per_engine_caps_usd"] == {}
        assert config["alert_threshold_pct"] == DEFAULT_ALERT_THRESHOLD_PCT

    def test_v2_full_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "v2.json"
        path.write_text(json.dumps({
            "monthly_cap_usd": 95.0,
            "per_engine_caps_usd": {
                "deepseek": 30.0,
                "mimo": 15.0,
                "qwen": 50.0,
            },
            "alert_threshold_pct": 75,
        }), encoding="utf-8")
        config = read_caps_config(cap_path=path)
        assert config["monthly_cap_usd"] == 95.0
        assert config["per_engine_caps_usd"]["deepseek"] == 30.0
        assert config["per_engine_caps_usd"]["mimo"] == 15.0
        assert config["per_engine_caps_usd"]["qwen"] == 50.0
        assert config["alert_threshold_pct"] == 75

    def test_garbage_file_returns_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "garbage.json"
        path.write_text("{not valid json", encoding="utf-8")
        config = read_caps_config(cap_path=path)
        assert config["monthly_cap_usd"] == 0.0
        assert config["per_engine_caps_usd"] == {}

    def test_alert_pct_clamped_to_range(self, tmp_path: Path) -> None:
        path = tmp_path / "bad-alert.json"
        path.write_text(json.dumps({
            "monthly_cap_usd": 10,
            "alert_threshold_pct": 150,
        }), encoding="utf-8")
        config = read_caps_config(cap_path=path)
        assert config["alert_threshold_pct"] == 100
        # And below 0 clamps to 0
        path.write_text(json.dumps({
            "monthly_cap_usd": 10,
            "alert_threshold_pct": -5,
        }), encoding="utf-8")
        config = read_caps_config(cap_path=path)
        assert config["alert_threshold_pct"] == 0


class TestWriteCapsConfig:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        write_caps_config({
            "monthly_cap_usd": 95.0,
            "per_engine_caps_usd": {"deepseek": 30, "mimo": 15},
            "alert_threshold_pct": 80,
        }, cap_path=path)
        config = read_caps_config(cap_path=path)
        assert config["monthly_cap_usd"] == 95.0
        assert config["per_engine_caps_usd"]["deepseek"] == 30
        assert config["alert_threshold_pct"] == 80

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "deeper" / "caps.json"
        write_caps_config({"monthly_cap_usd": 10}, cap_path=path)
        assert path.exists()


# ---------------------------------------------------------------------------
# set_engine_cap
# ---------------------------------------------------------------------------


class TestSetEngineCap:
    def test_add_new_engine_cap(self, tmp_path: Path) -> None:
        path = tmp_path / "caps.json"
        set_engine_cap("qwen", 50.0, cap_path=path)
        config = read_caps_config(cap_path=path)
        assert config["per_engine_caps_usd"]["qwen"] == 50.0

    def test_update_existing_cap(self, tmp_path: Path) -> None:
        path = tmp_path / "caps.json"
        set_engine_cap("qwen", 50.0, cap_path=path)
        set_engine_cap("qwen", 75.0, cap_path=path)
        config = read_caps_config(cap_path=path)
        assert config["per_engine_caps_usd"]["qwen"] == 75.0

    def test_zero_removes_cap(self, tmp_path: Path) -> None:
        path = tmp_path / "caps.json"
        set_engine_cap("qwen", 50.0, cap_path=path)
        set_engine_cap("qwen", 0.0, cap_path=path)
        config = read_caps_config(cap_path=path)
        assert "qwen" not in config["per_engine_caps_usd"]

    def test_preserves_other_engines(self, tmp_path: Path) -> None:
        path = tmp_path / "caps.json"
        set_engine_cap("deepseek", 30, cap_path=path)
        set_engine_cap("mimo", 15, cap_path=path)
        set_engine_cap("qwen", 50, cap_path=path)
        # Update one, others should remain
        set_engine_cap("mimo", 20, cap_path=path)
        config = read_caps_config(cap_path=path)
        assert config["per_engine_caps_usd"]["deepseek"] == 30
        assert config["per_engine_caps_usd"]["mimo"] == 20
        assert config["per_engine_caps_usd"]["qwen"] == 50

    def test_preserves_global_cap(self, tmp_path: Path) -> None:
        path = tmp_path / "caps.json"
        write_caps_config({
            "monthly_cap_usd": 195,
            "per_engine_caps_usd": {},
        }, cap_path=path)
        set_engine_cap("qwen", 50, cap_path=path)
        config = read_caps_config(cap_path=path)
        assert config["monthly_cap_usd"] == 195


# ---------------------------------------------------------------------------
# _spent_this_month_by_engine canonicalization
# ---------------------------------------------------------------------------


def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestSpentByEngineCanonicalization:
    def test_swarm_prefix_folds_to_canonical(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="t1", engine="swarm/kimi",
                        input_tokens=100, output_tokens=200,
                        ledger_path=ledger)
        spent = _spent_this_month_by_engine(ledger_path=ledger)
        # kimi is a normal engine; swarm/ stripped; cap-key is "kimi"
        assert "kimi" in spent
        assert "swarm/kimi" not in spent

    def test_deepseek_variants_fold(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        for engine in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek"):
            record_dispatch(task_id="t1", engine=engine,
                            input_tokens=1_000_000, output_tokens=0,
                            ledger_path=ledger)
        spent = _spent_this_month_by_engine(ledger_path=ledger)
        # v4-pro normalizes to deepseek-pro, but the cap-key strips -pro suffix
        # so both should fall under "deepseek"
        assert "deepseek" in spent
        assert spent["deepseek"] > 0
        # No deepseek-pro key separately under the cap scheme
        assert "deepseek-pro" not in spent

    def test_mimo_sub_variants_fold_to_mimo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # tp- key triggers the mimo-sub normalization
        monkeypatch.setenv("MIMO_API_KEY", "tp-test-key-abc123")
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="t1", engine="mimo-v2.5-pro",
                        input_tokens=1000, output_tokens=1000,
                        ledger_path=ledger)
        record_dispatch(task_id="t2", engine="mimo",
                        input_tokens=1000, output_tokens=1000,
                        ledger_path=ledger)
        spent = _spent_this_month_by_engine(ledger_path=ledger)
        # Both fold to "mimo" for cap purposes (strip -sub, strip -pro)
        assert "mimo" in spent
        assert "mimo-sub" not in spent
        assert "mimo-pro-sub" not in spent
        assert "mimo-pro" not in spent

    def test_excludes_other_months(self, tmp_path: Path) -> None:
        """Entries from prior months should not count toward current cap."""
        ledger = tmp_path / "ledger.jsonl"
        # Write an entry from 2 months ago manually
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        ledger.write_text(json.dumps({
            "timestamp": old_ts,
            "task_id": "old",
            "engine": "deepseek",
            "model": "deepseek-v4-flash",
            "input_tokens": 10_000_000,
            "output_tokens": 10_000_000,
            "latency_ms": 0,
            "cost_usd": 100.0,
        }) + "\n", encoding="utf-8")
        spent = _spent_this_month_by_engine(ledger_path=ledger)
        # 60-day-old entry filtered out — only this month
        assert spent.get("deepseek", 0.0) == 0.0


# ---------------------------------------------------------------------------
# check_engine_cap
# ---------------------------------------------------------------------------


class TestCheckEngineCap:
    def test_no_cap_configured_returns_within(self, tmp_path: Path) -> None:
        config = {"per_engine_caps_usd": {}, "alert_threshold_pct": 80}
        status = check_engine_cap(
            "deepseek",
            ledger_path=tmp_path / "missing.jsonl",
            caps_config=config,
        )
        assert status.within_cap is True
        assert status.cap_usd == 0.0
        assert status.alert_threshold_reached is False

    def test_within_cap_under_threshold(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        # spend $1 at deepseek rate (1M input tokens at $0.27/M)
        record_dispatch(task_id="t1", engine="deepseek",
                        input_tokens=1_000_000, output_tokens=0,
                        ledger_path=ledger)
        config = {"per_engine_caps_usd": {"deepseek": 30.0},
                  "alert_threshold_pct": 80}
        status = check_engine_cap(
            "deepseek", ledger_path=ledger, caps_config=config,
        )
        assert status.within_cap is True
        assert status.alert_threshold_reached is False
        assert status.pct_used < 80
        assert status.cap_usd == 30.0

    def test_at_alert_threshold(self, tmp_path: Path) -> None:
        """At 80% spend, alert_threshold_reached should be True but
        within_cap still True."""
        ledger = tmp_path / "ledger.jsonl"
        # Spend $24 (80% of $30 cap) — at $0.27/M input rate
        # 24 / 0.27 = ~88.9M input tokens
        record_dispatch(task_id="t1", engine="deepseek",
                        input_tokens=88_888_889, output_tokens=0,
                        ledger_path=ledger)
        config = {"per_engine_caps_usd": {"deepseek": 30.0},
                  "alert_threshold_pct": 80}
        status = check_engine_cap(
            "deepseek", ledger_path=ledger, caps_config=config,
        )
        assert status.within_cap is True
        assert status.alert_threshold_reached is True
        assert status.pct_used >= 80

    def test_over_cap(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        # Spend $100 — way over $30 cap
        record_dispatch(task_id="t1", engine="deepseek",
                        input_tokens=400_000_000, output_tokens=0,
                        ledger_path=ledger)
        config = {"per_engine_caps_usd": {"deepseek": 30.0},
                  "alert_threshold_pct": 80}
        status = check_engine_cap(
            "deepseek", ledger_path=ledger, caps_config=config,
        )
        assert status.within_cap is False
        assert status.alert_threshold_reached is True
        assert status.pct_used > 100

    def test_canonicalizes_engine_name(self, tmp_path: Path) -> None:
        """A cap configured for "deepseek" applies to "swarm/deepseek-v4-flash"
        dispatches too."""
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="t1", engine="swarm/deepseek-v4-flash",
                        input_tokens=1_000_000, output_tokens=0,
                        ledger_path=ledger)
        config = {"per_engine_caps_usd": {"deepseek": 30.0},
                  "alert_threshold_pct": 80}
        status = check_engine_cap(
            "deepseek", ledger_path=ledger, caps_config=config,
        )
        assert status.spent_usd > 0  # swarm/ stripped, folded to deepseek


# ---------------------------------------------------------------------------
# enforce_engine_cap
# ---------------------------------------------------------------------------


class TestEnforceEngineCap:
    def test_within_cap_returns_status(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        config = {"per_engine_caps_usd": {"deepseek": 30.0},
                  "alert_threshold_pct": 80}
        status = enforce_engine_cap(
            "deepseek", ledger_path=ledger, caps_config=config,
        )
        assert status.within_cap is True

    def test_over_cap_raises(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        # Force over-cap spending
        record_dispatch(task_id="t1", engine="deepseek",
                        input_tokens=400_000_000, output_tokens=0,
                        ledger_path=ledger)
        config = {"per_engine_caps_usd": {"deepseek": 30.0},
                  "alert_threshold_pct": 80}
        with pytest.raises(CapExceededError) as exc_info:
            enforce_engine_cap(
                "deepseek", ledger_path=ledger, caps_config=config,
            )
        # Error message includes engine + spend + cap for operator visibility
        msg = str(exc_info.value)
        assert "deepseek" in msg
        assert "$30" in msg
        assert "%" in msg

    def test_no_cap_configured_doesnt_raise(self, tmp_path: Path) -> None:
        """If no cap is set for an engine, enforce_engine_cap should not
        raise even with massive spend."""
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="t1", engine="deepseek",
                        input_tokens=400_000_000, output_tokens=0,
                        ledger_path=ledger)
        config = {"per_engine_caps_usd": {}, "alert_threshold_pct": 80}
        # Should not raise — no cap means no enforcement
        status = enforce_engine_cap(
            "deepseek", ledger_path=ledger, caps_config=config,
        )
        assert status.within_cap is True


# ---------------------------------------------------------------------------
# all_engines_status
# ---------------------------------------------------------------------------


class TestAllEnginesStatus:
    def test_includes_capped_and_spending_engines(
        self, tmp_path: Path,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="t1", engine="deepseek",
                        input_tokens=1_000_000, output_tokens=0,
                        ledger_path=ledger)
        config = {
            "per_engine_caps_usd": {
                "deepseek": 30.0,
                "mimo": 15.0,
                "qwen": 50.0,  # no spend yet but capped — still shown
            },
            "alert_threshold_pct": 80,
        }
        rows = all_engines_status(ledger_path=ledger, caps_config=config)
        engines = {r.engine for r in rows}
        assert engines == {"deepseek", "mimo", "qwen"}

    def test_sorted_by_engine_name(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        config = {
            "per_engine_caps_usd": {
                "zeta-engine": 10,
                "alpha-engine": 10,
                "mu-engine": 10,
            },
            "alert_threshold_pct": 80,
        }
        rows = all_engines_status(ledger_path=ledger, caps_config=config)
        assert [r.engine for r in rows] == [
            "alpha-engine", "mu-engine", "zeta-engine",
        ]


# ---------------------------------------------------------------------------
# CLI verbs
# ---------------------------------------------------------------------------


class TestBudgetCapsCli:
    def test_help_lists_caps_subcommand(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "--help"])
        assert result.exit_code == 0
        assert "caps" in result.output
        assert "set-engine-cap" in result.output

    def test_caps_empty_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["budget", "caps"])
        assert result.exit_code == 0
        # No caps + no spend ⇒ helpful message
        assert "no per-engine caps configured" in result.output.lower() \
               or "not configured" in result.output.lower()

    def test_caps_json_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # Set a cap
        runner = CliRunner()
        runner.invoke(cli, ["budget", "set-engine-cap", "deepseek", "30"])
        result = runner.invoke(cli, ["budget", "caps", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "global" in data
        assert "engines" in data
        eng_entries = {e["engine"]: e for e in data["engines"]}
        assert "deepseek" in eng_entries
        assert eng_entries["deepseek"]["cap_usd"] == 30.0


class TestBudgetSetEngineCapCli:
    def test_set_cap_writes_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["budget", "set-engine-cap", "qwen", "50"],
        )
        assert result.exit_code == 0
        assert "50.00" in result.output
        # File written
        cap_file = tmp_path / "coord" / "dev_loop" / "budget_cap.json"
        assert cap_file.exists()
        data = json.loads(cap_file.read_text(encoding="utf-8"))
        assert data["per_engine_caps_usd"]["qwen"] == 50.0

    def test_set_cap_zero_removes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["budget", "set-engine-cap", "qwen", "50"])
        result = runner.invoke(
            cli, ["budget", "set-engine-cap", "qwen", "0"],
        )
        assert result.exit_code == 0
        assert "removed" in result.output.lower()
        cap_file = tmp_path / "coord" / "dev_loop" / "budget_cap.json"
        data = json.loads(cap_file.read_text(encoding="utf-8"))
        assert "qwen" not in data["per_engine_caps_usd"]

    def test_set_global_cap_preserves_per_engine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """W14-BUDGET-METER-PER-ENGINE: ``set-cap`` must not erase
        per-engine caps that were set previously.  This is the
        regression test for the v1→v2 schema migration."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["budget", "set-engine-cap", "deepseek", "30"])
        runner.invoke(cli, ["budget", "set-cap", "95"])
        cap_file = tmp_path / "coord" / "dev_loop" / "budget_cap.json"
        data = json.loads(cap_file.read_text(encoding="utf-8"))
        # Both caps coexist
        assert data["monthly_cap_usd"] == 95.0
        assert data["per_engine_caps_usd"]["deepseek"] == 30.0


# ---------------------------------------------------------------------------
# Backward compat with old check_cap
# ---------------------------------------------------------------------------


class TestCheckCapBackwardCompat:
    def test_v1_schema_still_works(self, tmp_path: Path) -> None:
        """Old check_cap callers passing monthly_cap_usd explicitly still work."""
        ledger = tmp_path / "ledger.jsonl"
        # Don't use the on-disk DEFAULT_CAP_PATH for this test
        within, spent, cap = check_cap(
            monthly_cap_usd=100.0, ledger_path=ledger,
        )
        assert within is True
        assert cap == 100.0
        assert spent == 0.0
