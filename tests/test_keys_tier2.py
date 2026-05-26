"""W14-KEYS-POOL-TIER2 2026-05-26: tests for per-key health + policy + CLI."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.keys import (
    DEFAULT_STRATEGY,
    VALID_STRATEGIES,
    alias_status_summary,
    get_strategy,
    is_alias_healthy,
    list_strategies,
    pick_next_key,
    record_outcome,
    reset_alias_history,
    set_strategy,
    unhealthy_aliases,
)
from harness.keys import health as health_mod
from harness.keys import policy as policy_mod
from harness.keys.resolve import reset_rotation_counter


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Point health ledger + policy file at tmp_path so tests don't
    # touch the real coord/key_health.jsonl or .harness/key_policy.json
    monkeypatch.setattr(
        health_mod, "_ledger_path", lambda: tmp_path / "key_health.jsonl",
    )
    monkeypatch.setattr(
        policy_mod, "_policy_path", lambda: tmp_path / "key_policy.json",
    )
    for prefix in ("KIMI_API_KEY", "MIMO_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(prefix, raising=False)
        for n in range(1, 6):
            monkeypatch.delenv(f"{prefix}_{n}", raising=False)
            monkeypatch.delenv(f"{prefix}_LABEL_{n}", raising=False)
    reset_rotation_counter()


# ---------------------------------------------------------------------------
# Health ledger
# ---------------------------------------------------------------------------


class TestHealthLedger:
    def test_record_and_read_back(self, tmp_path: Path) -> None:
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY",
            "up", source="probe",
        )
        summary = alias_status_summary("KIMI_API_KEY")
        assert "k1" in summary
        assert summary["k1"]["category"] == "up"
        assert summary["k1"]["healthy"] is True

    def test_no_record_means_healthy(self) -> None:
        # Innocent until proven guilty
        assert is_alias_healthy("KIMI_API_KEY", "k1") is True

    def test_persistent_fail_quarantines(self) -> None:
        record_outcome(
            "KIMI_API_KEY", "k2", "KIMI_API_KEY_2",
            "auth-failed", source="probe",
        )
        assert is_alias_healthy("KIMI_API_KEY", "k2") is False
        assert "k2" in unhealthy_aliases("KIMI_API_KEY")

    def test_quota_exceeded_quarantines(self) -> None:
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY",
            "quota-exceeded", source="dispatch",
        )
        assert is_alias_healthy("KIMI_API_KEY", "k1") is False

    def test_terminated_quarantines(self) -> None:
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY",
            "terminated", source="probe",
        )
        assert is_alias_healthy("KIMI_API_KEY", "k1") is False

    def test_up_supersedes_prior_fail(self) -> None:
        # Newer "up" record makes the alias healthy again
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY",
            "auth-failed", source="probe",
        )
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY",
            "up", source="probe",
        )
        assert is_alias_healthy("KIMI_API_KEY", "k1") is True

    def test_transient_decays_in_30min(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # Write a transient failure with a timestamp from 31 minutes ago
        old_ts = (datetime.now(timezone.utc)
                  - timedelta(minutes=31)).isoformat().replace(
                      "+00:00", "Z",
                  )
        ledger = tmp_path / "key_health.jsonl"
        ledger.write_text(
            json.dumps({
                "ts": old_ts, "env_prefix": "KIMI_API_KEY",
                "alias": "k1", "env_var": "KIMI_API_KEY",
                "category": "transient", "source": "dispatch",
                "details": "",
            }) + "\n",
            encoding="utf-8",
        )
        assert is_alias_healthy("KIMI_API_KEY", "k1") is True

    def test_persistent_does_not_decay_in_30min(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # Auth-failed 31 min ago is still quarantined (24h window)
        old_ts = (datetime.now(timezone.utc)
                  - timedelta(minutes=31)).isoformat().replace(
                      "+00:00", "Z",
                  )
        ledger = tmp_path / "key_health.jsonl"
        ledger.write_text(
            json.dumps({
                "ts": old_ts, "env_prefix": "KIMI_API_KEY",
                "alias": "k1", "env_var": "KIMI_API_KEY",
                "category": "auth-failed", "source": "probe",
                "details": "",
            }) + "\n",
            encoding="utf-8",
        )
        assert is_alias_healthy("KIMI_API_KEY", "k1") is False

    def test_persistent_decays_after_24h(self, tmp_path: Path) -> None:
        old_ts = (datetime.now(timezone.utc)
                  - timedelta(hours=25)).isoformat().replace(
                      "+00:00", "Z",
                  )
        ledger = tmp_path / "key_health.jsonl"
        ledger.write_text(
            json.dumps({
                "ts": old_ts, "env_prefix": "KIMI_API_KEY",
                "alias": "k1", "env_var": "KIMI_API_KEY",
                "category": "auth-failed", "source": "probe",
                "details": "",
            }) + "\n",
            encoding="utf-8",
        )
        # After 24h the alias is "forgiven" → considered healthy
        assert is_alias_healthy("KIMI_API_KEY", "k1") is True

    def test_reset_drops_history(self) -> None:
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY",
            "auth-failed", source="probe",
        )
        n = reset_alias_history("KIMI_API_KEY", "k1")
        assert n == 1
        # And after reset, alias is healthy
        assert is_alias_healthy("KIMI_API_KEY", "k1") is True

    def test_reset_only_affects_target_alias(self) -> None:
        record_outcome("KIMI_API_KEY", "k1", "KIMI_API_KEY",
                       "auth-failed", source="probe")
        record_outcome("KIMI_API_KEY", "k2", "KIMI_API_KEY_2",
                       "auth-failed", source="probe")
        record_outcome("MIMO_API_KEY", "k1", "MIMO_API_KEY",
                       "auth-failed", source="probe")
        reset_alias_history("KIMI_API_KEY", "k1")
        # k1 of Kimi is fresh; k2 of Kimi still down; MIMO untouched
        assert is_alias_healthy("KIMI_API_KEY", "k1") is True
        assert is_alias_healthy("KIMI_API_KEY", "k2") is False
        assert is_alias_healthy("MIMO_API_KEY", "k1") is False


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class TestPolicy:
    def test_default_is_rotation(self) -> None:
        assert get_strategy("KIMI_API_KEY") == "rotation"
        assert DEFAULT_STRATEGY == "rotation"

    def test_set_persists(self) -> None:
        set_strategy("KIMI_API_KEY", "priority")
        assert get_strategy("KIMI_API_KEY") == "priority"

    def test_set_isolates_per_provider(self) -> None:
        set_strategy("KIMI_API_KEY", "priority")
        set_strategy("MIMO_API_KEY", "failover-only")
        assert get_strategy("KIMI_API_KEY") == "priority"
        assert get_strategy("MIMO_API_KEY") == "failover-only"
        assert get_strategy("DEEPSEEK_API_KEY") == "rotation"  # default

    def test_invalid_strategy_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_strategy("KIMI_API_KEY", "random-walk")

    def test_valid_strategies_set(self) -> None:
        assert VALID_STRATEGIES == frozenset({
            "rotation", "priority", "failover-only",
        })

    def test_list_all(self) -> None:
        set_strategy("KIMI_API_KEY", "priority")
        all_set = list_strategies()
        assert all_set == {"KIMI_API_KEY": "priority"}


# ---------------------------------------------------------------------------
# pick_next_key honors health + policy
# ---------------------------------------------------------------------------


class TestPickNextKeyHealthAware:
    def test_unhealthy_alias_excluded_automatically(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY_1",
            "auth-failed", source="probe",
        )
        # Rotation should land on k2 since k1 is unhealthy
        result = pick_next_key("KIMI_API_KEY", strategy="rotation")
        assert result.alias == "k2"

    def test_honor_health_false_ignores_quarantine(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY_1",
            "auth-failed", source="probe",
        )
        # With honor_health=False we get k1 anyway (e.g. emergency bypass)
        reset_rotation_counter()
        result = pick_next_key(
            "KIMI_API_KEY", strategy="rotation", honor_health=False,
        )
        assert result.alias == "k1"

    def test_no_strategy_reads_policy(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        set_strategy("KIMI_API_KEY", "priority")
        result = pick_next_key("KIMI_API_KEY")  # strategy=None
        # priority means lowest-slot first
        assert result.alias == "k1"

    def test_all_aliases_unhealthy_returns_none(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY_1",
            "auth-failed", source="probe",
        )
        record_outcome(
            "KIMI_API_KEY", "k2", "KIMI_API_KEY_2",
            "terminated", source="probe",
        )
        result = pick_next_key("KIMI_API_KEY")
        assert result is None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestPolicyCli:
    def test_policy_get_default(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "policy", "get"])
        assert result.exit_code == 0
        assert "rotation" in result.output
        assert "(default)" in result.output

    def test_policy_set_then_get(self) -> None:
        runner = CliRunner()
        r1 = runner.invoke(
            cli, ["keys", "policy", "set", "KIMI_API_KEY", "priority"],
        )
        assert r1.exit_code == 0
        r2 = runner.invoke(cli, ["keys", "policy", "get", "KIMI_API_KEY"])
        assert r2.exit_code == 0
        assert "priority" in r2.output

    def test_policy_set_rejects_unknown_provider(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["keys", "policy", "set", "BOGUS_KEY", "priority"],
        )
        assert result.exit_code == 1
        assert "unknown env_prefix" in result.output.lower() or \
               "unknown env_prefix" in (result.stderr_bytes or b"").decode(
                   "utf-8", errors="ignore"
               ).lower()

    def test_policy_set_rejects_bad_strategy(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["keys", "policy", "set", "KIMI_API_KEY", "random-walk"],
        )
        # Click's Choice validation kicks in BEFORE our handler
        assert result.exit_code != 0


class TestForgetCli:
    def test_forget_drops_history(self) -> None:
        # First record a fail
        record_outcome(
            "KIMI_API_KEY", "k2", "KIMI_API_KEY_2",
            "auth-failed", source="probe",
        )
        assert is_alias_healthy("KIMI_API_KEY", "k2") is False
        # Now forget it via CLI
        runner = CliRunner()
        result = runner.invoke(
            cli, ["keys", "forget", "KIMI_API_KEY", "k2"],
        )
        assert result.exit_code == 0
        assert "1 record" in result.output
        # Alias is now considered healthy
        assert is_alias_healthy("KIMI_API_KEY", "k2") is True


class TestProbeAllCli:
    def test_probe_all_skips_providers_without_engine_probe(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No keys configured for any provider → no-keys outcomes
        runner = CliRunner()
        # Patch probe_engine_live so we don't actually hit the network
        def fake_probe(name, log=False):  # noqa: ARG001
            return "endpoint-down", "no key configured"
        monkeypatch.setattr(
            "harness.cli_helpers.probe_engine_live", fake_probe,
        )
        result = runner.invoke(cli, ["keys", "probe-all"])
        # exit 0 (all "no-keys") or 1 (any failing)
        assert result.exit_code in (0, 1)
        # Output should be the table header
        assert "provider" in result.output.lower()

    def test_probe_all_json_format(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY", "sk-fake")

        def fake_probe(name, log=False):  # noqa: ARG001
            return "up", ""
        monkeypatch.setattr(
            "harness.cli_helpers.probe_engine_live", fake_probe,
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["keys", "probe-all", "--format", "json",
             "--provider", "KIMI_API_KEY"],
        )
        # All up → exit 0
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        kimi = [r for r in data if r["env_prefix"] == "KIMI_API_KEY"]
        assert len(kimi) >= 1
        assert kimi[0]["up"] is True
