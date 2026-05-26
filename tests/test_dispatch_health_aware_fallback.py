"""W14-DISPATCH-HEALTH-AWARE-FALLBACK: tests for the routing filter.

Coverage:
  - _filter_disabled honors HARNESS_DISPATCH_SKIP_HEALTH_FILTER env
  - _keys_present reads env vars per API_KEY_ENV_VARS
  - _recently_terminated_engines parses probe log + applies window
  - filter_eligible_engines composes all three filters
  - describe_fallback_policy returns JSON-serializable snapshot
  - CLI verb: harness engines fallback-policy
  - Backward-compat: HARNESS_DISPATCH_SKIP_HEALTH_FILTER=1 disables all filters
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.engines.routing import (
    _filter_disabled,
    _keys_present,
    _recently_terminated_engines,
    describe_fallback_policy,
    filter_eligible_engines,
)


# ---------------------------------------------------------------------------
# _filter_disabled
# ---------------------------------------------------------------------------


class TestFilterDisabled:
    def test_default_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", raising=False)
        assert _filter_disabled() is False

    def test_env_var_1_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "1")
        assert _filter_disabled() is True

    def test_env_var_true_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "true")
        assert _filter_disabled() is True

    def test_env_var_yes_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "yes")
        assert _filter_disabled() is True

    def test_env_var_0_keeps_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "0")
        assert _filter_disabled() is False

    def test_env_var_garbage_keeps_enabled(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "maybe")
        assert _filter_disabled() is False


# ---------------------------------------------------------------------------
# _keys_present
# ---------------------------------------------------------------------------


class TestKeysPresent:
    def test_key_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-abc")
        result = _keys_present()
        assert result.get("deepseek") is True

    def test_key_empty_string_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "")
        result = _keys_present()
        assert result.get("deepseek") is False

    def test_key_whitespace_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "   ")
        result = _keys_present()
        assert result.get("deepseek") is False

    def test_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = _keys_present()
        assert result.get("anthropic") is False


# ---------------------------------------------------------------------------
# _recently_terminated_engines
# ---------------------------------------------------------------------------


def _make_probe_event(
    engine: str, category: str,
    *, hours_ago: float = 0.0,
) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "timestamp": ts,
        "engine": engine,
        "category": category,
        "error_excerpt": None,
        "latency_ms": 100,
    }


class TestRecentlyTerminatedEngines:
    def test_empty_log(self, tmp_path: Path) -> None:
        result = _recently_terminated_engines(
            log_path=tmp_path / "missing.jsonl",
        )
        assert result == set()

    def test_recent_terminated(self, tmp_path: Path) -> None:
        log = tmp_path / "probes.jsonl"
        log.write_text(
            json.dumps(_make_probe_event("kimi", "terminated", hours_ago=1))
            + "\n",
            encoding="utf-8",
        )
        result = _recently_terminated_engines(log_path=log)
        assert "kimi" in result

    def test_old_terminated_outside_window(self, tmp_path: Path) -> None:
        log = tmp_path / "probes.jsonl"
        log.write_text(
            json.dumps(_make_probe_event("kimi", "terminated", hours_ago=48))
            + "\n",
            encoding="utf-8",
        )
        result = _recently_terminated_engines(
            log_path=log, window_hours=24,
        )
        assert "kimi" not in result

    def test_recovered_engine_not_flagged(self, tmp_path: Path) -> None:
        """An engine with an 'up' probe AFTER a 'terminated' probe
        should not be flagged as terminated."""
        log = tmp_path / "probes.jsonl"
        # First terminated, then up — later up wins
        log.write_text(
            json.dumps(_make_probe_event("kimi", "terminated", hours_ago=10))
            + "\n"
            + json.dumps(_make_probe_event("kimi", "up", hours_ago=1))
            + "\n",
            encoding="utf-8",
        )
        result = _recently_terminated_engines(log_path=log)
        assert "kimi" not in result

    def test_multiple_engines(self, tmp_path: Path) -> None:
        log = tmp_path / "probes.jsonl"
        log.write_text(
            json.dumps(_make_probe_event("kimi", "terminated", hours_ago=1))
            + "\n"
            + json.dumps(_make_probe_event("deepseek", "up", hours_ago=1))
            + "\n"
            + json.dumps(_make_probe_event("mimo", "auth-failed", hours_ago=1))
            + "\n",
            encoding="utf-8",
        )
        result = _recently_terminated_engines(log_path=log)
        assert result == {"kimi"}  # auth-failed not terminated

    def test_garbage_lines_skipped(self, tmp_path: Path) -> None:
        log = tmp_path / "probes.jsonl"
        log.write_text(
            "not json at all\n"
            + json.dumps(_make_probe_event("kimi", "terminated", hours_ago=1))
            + "\n"
            + "\n"  # empty line
            + json.dumps({"timestamp": "not-iso", "engine": "x",
                          "category": "terminated"}) + "\n",
            encoding="utf-8",
        )
        result = _recently_terminated_engines(log_path=log)
        # Only the valid kimi entry counts
        assert result == {"kimi"}


# ---------------------------------------------------------------------------
# filter_eligible_engines
# ---------------------------------------------------------------------------


class TestFilterEligibleEngines:
    def test_filter_disabled_returns_input(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "1")
        engines = ["deepseek", "kimi", "anthropic"]
        eligible, reasons = filter_eligible_engines(engines)
        assert eligible == engines
        assert reasons == {}

    def test_skip_no_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        eligible, reasons = filter_eligible_engines(
            ["deepseek", "anthropic"],
            skip_terminated=False,
            skip_over_budget=False,
        )
        assert eligible == ["deepseek"]
        assert reasons == {"anthropic": "no-key"}

    def test_skip_terminated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", raising=False)
        log = tmp_path / "probes.jsonl"
        log.write_text(
            json.dumps(_make_probe_event("kimi", "terminated", hours_ago=1))
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("KIMI_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        eligible, reasons = filter_eligible_engines(
            ["deepseek", "kimi"],
            skip_no_key=False,
            skip_over_budget=False,
            health_probe_log_path=log,
        )
        assert eligible == ["deepseek"]
        assert reasons.get("kimi") == "terminated"

    def test_skip_over_budget(self, tmp_path: Path) -> None:
        from harness.budget import record_dispatch
        ledger = tmp_path / "ledger.jsonl"
        # Spend $100 on deepseek (massive over a $30 cap)
        record_dispatch(task_id="t1", engine="deepseek",
                        input_tokens=400_000_000, output_tokens=0,
                        ledger_path=ledger)
        caps_config = {
            "per_engine_caps_usd": {"deepseek": 30.0},
            "alert_threshold_pct": 80,
        }
        eligible, reasons = filter_eligible_engines(
            ["deepseek", "mimo"],
            skip_no_key=False,
            skip_terminated=False,
            budget_ledger_path=ledger,
            budget_caps_config=caps_config,
        )
        assert "deepseek" not in eligible
        assert "over-cap" in reasons["deepseek"]
        # mimo has no cap configured ⇒ eligible
        assert "mimo" in eligible

    def test_preserves_input_order(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "1")
        eligible, _ = filter_eligible_engines(["c", "a", "b"])
        assert eligible == ["c", "a", "b"]

    def test_all_three_filters_compose(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Combination test: anthropic no-key + kimi terminated +
        deepseek over-cap ⇒ all skipped, mimo eligible."""
        monkeypatch.delenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("KIMI_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("MIMO_API_KEY", "sk-test")
        log = tmp_path / "probes.jsonl"
        log.write_text(
            json.dumps(_make_probe_event("kimi", "terminated", hours_ago=1))
            + "\n",
            encoding="utf-8",
        )
        from harness.budget import record_dispatch
        ledger = tmp_path / "ledger.jsonl"
        record_dispatch(task_id="t1", engine="deepseek",
                        input_tokens=400_000_000, output_tokens=0,
                        ledger_path=ledger)
        caps_config = {
            "per_engine_caps_usd": {"deepseek": 30.0},
            "alert_threshold_pct": 80,
        }
        eligible, reasons = filter_eligible_engines(
            ["anthropic", "kimi", "deepseek", "mimo"],
            health_probe_log_path=log,
            budget_ledger_path=ledger,
            budget_caps_config=caps_config,
        )
        assert eligible == ["mimo"]
        assert reasons["anthropic"] == "no-key"
        assert reasons["kimi"] == "terminated"
        assert "over-cap" in reasons["deepseek"]


# ---------------------------------------------------------------------------
# describe_fallback_policy
# ---------------------------------------------------------------------------


class TestDescribeFallbackPolicy:
    def test_returns_json_serializable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "1")
        policy = describe_fallback_policy(
            engines=["deepseek", "kimi"],
        )
        # Should round-trip through JSON
        serialized = json.dumps(policy)
        parsed = json.loads(serialized)
        assert "filter_disabled" in parsed
        assert "all_engines" in parsed
        assert "eligible" in parsed
        assert "skipped" in parsed

    def test_default_to_supported_backends(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "1")
        policy = describe_fallback_policy()
        # Should NOT include "mock" — non-production backend
        assert "mock" not in policy["all_engines"]
        # Should include the standard production engines
        for eng in ("deepseek", "kimi", "anthropic", "gemini", "mimo"):
            assert eng in policy["all_engines"]


# ---------------------------------------------------------------------------
# CLI: harness engines fallback-policy
# ---------------------------------------------------------------------------


class TestFallbackPolicyCli:
    def test_help_lists_subcommand(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "--help"])
        assert result.exit_code == 0
        assert "fallback-policy" in result.output \
               or "failures" in result.output

    def test_runs_without_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # Disable filter to keep test deterministic regardless of env
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "1")
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "fallback-policy"])
        assert result.exit_code == 0
        assert "Filter enabled" in result.output

    def test_shows_skip_reasons(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(
            "HARNESS_DISPATCH_SKIP_HEALTH_FILTER", raising=False,
        )
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("MIMO_API_KEY", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "fallback-policy"])
        assert result.exit_code == 0
        # With no keys at all, every engine skipped with "no-key" reason
        assert "no-key" in result.output


# ---------------------------------------------------------------------------
# Regression: existing dispatch path tests should still pass with filter
# ---------------------------------------------------------------------------


class TestDispatcherIntegration:
    def test_filter_skipped_when_env_var_set(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When HARNESS_DISPATCH_SKIP_HEALTH_FILTER=1, the dispatcher
        should fall through to its original behavior (engine ordering
        unchanged, no skips).  This is the safety hatch for tests +
        operator overrides."""
        monkeypatch.setenv("HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "1")
        # With filter disabled, all engines pass through unchanged
        eligible, reasons = filter_eligible_engines(
            ["anthropic", "kimi", "deepseek", "gemini", "mimo"],
        )
        assert eligible == ["anthropic", "kimi", "deepseek", "gemini", "mimo"]
        assert reasons == {}
