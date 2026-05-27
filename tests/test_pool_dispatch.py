"""W14-KEYS-POOL-P2 2026-05-26: integration tests for pool-aware
dispatch with health-aware failover.

The audit panel (W14-PANEL-CONVERSATION-AUDIT) specifically flagged
that the resolver was unit-tested but the FULL dispatch path was
not.  These tests close that gap by exercising dispatch_with_pool
end-to-end with mocked engines so we can simulate auth failures
and assert the failover path.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.engines.base import EngineResponse
from harness.engines.pool_dispatch import (
    PoolAttempt,
    PoolDispatchResult,
    _classify_failure,
    dispatch_with_pool,
)
from harness.keys import (
    alias_status_summary,
    record_outcome,
)
from harness.keys import health as health_mod
from harness.keys import policy as policy_mod
from harness.keys.resolve import reset_rotation_counter


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Each test starts with a clean health ledger + policy + env."""
    monkeypatch.setattr(
        health_mod, "_ledger_path",
        lambda: tmp_path / "key_health.jsonl",
    )
    monkeypatch.setenv(
        "HARNESS_KEY_POLICY_PATH",
        str(tmp_path / "key_policy.json"),
    )
    for prefix in ("KIMI_API_KEY", "MIMO_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(prefix, raising=False)
        for n in range(1, 6):
            monkeypatch.delenv(f"{prefix}_{n}", raising=False)
    reset_rotation_counter()


def _make_engine(success: bool, error: str = "", text: str = "OK"):
    """Build a mock engine whose dispatch() returns the canned response."""
    eng = MagicMock()
    eng.dispatch.return_value = EngineResponse(
        success=success, text=text if success else "",
        latency_ms=100,
        error=error if not success else "",
    )
    return eng


# ---------------------------------------------------------------------------
# _classify_failure
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    def test_success_classified_as_up(self) -> None:
        resp = EngineResponse(success=True, text="OK", latency_ms=10)
        assert _classify_failure(resp) == "up"

    def test_auth_error_classified(self) -> None:
        for err in [
            "401 Unauthorized",
            "invalid api key",
            "auth failed",
            "403 Forbidden",
        ]:
            resp = EngineResponse(
                success=False, text="", latency_ms=0, error=err,
            )
            assert _classify_failure(resp) == "auth-failed", (
                f"failed on {err!r}"
            )

    def test_quota_classified(self) -> None:
        for err in [
            "429 rate limit exceeded",
            "quota exceeded",
            "monthly credit limit hit",
        ]:
            resp = EngineResponse(
                success=False, text="", latency_ms=0, error=err,
            )
            assert _classify_failure(resp) == "quota-exceeded", (
                f"failed on {err!r}"
            )

    def test_terminated_classified(self) -> None:
        for err in ["account terminated", "account suspended"]:
            resp = EngineResponse(
                success=False, text="", latency_ms=0, error=err,
            )
            assert _classify_failure(resp) == "terminated"

    def test_transient_classified(self) -> None:
        for err in [
            "timeout after 90s",
            "connection refused",
            "503 service unavailable",
        ]:
            resp = EngineResponse(
                success=False, text="", latency_ms=0, error=err,
            )
            assert _classify_failure(resp) == "transient"

    def test_unknown_classified(self) -> None:
        resp = EngineResponse(
            success=False, text="", latency_ms=0,
            error="something weird went wrong",
        )
        assert _classify_failure(resp) == "unknown-failure"


# ---------------------------------------------------------------------------
# Integration: pool-aware dispatch
# ---------------------------------------------------------------------------


class TestPoolDispatchFailover:
    """W14-PANEL-AUDIT 2026-05-26: the integration test the audit
    panel said was missing.  Configures 2 keys, first invalid,
    dispatches via the pool, asserts failover."""

    def test_first_key_fails_second_succeeds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Two keys configured: k1 will fail auth, k2 will succeed
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-bad-key")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-good-key")

        engines_by_key = {
            "sk-bad-key": _make_engine(
                success=False,
                error="401 Unauthorized: invalid api key",
            ),
            "sk-good-key": _make_engine(success=True, text="hello"),
        }

        def builder(provider, api_key):
            return engines_by_key[api_key]

        result = dispatch_with_pool(
            "kimi-via-claude",
            "test prompt",
            engine_builder=builder,
            strategy="priority",  # deterministic: always k1 first
        )

        # Headline: pool dispatch succeeded
        assert result.success is True
        assert result.winning_alias == "k2"
        assert result.response.text == "hello"

        # Both keys were tried, in order
        assert len(result.attempts) == 2
        assert result.attempts[0].alias == "k1"
        assert result.attempts[0].success is False
        assert result.attempts[0].category == "auth-failed"
        assert result.attempts[1].alias == "k2"
        assert result.attempts[1].success is True

        # Health ledger reflects both outcomes
        summary = alias_status_summary("KIMI_API_KEY")
        assert summary["k1"]["category"] == "auth-failed"
        assert summary["k1"]["healthy"] is False
        assert summary["k2"]["category"] == "up"
        assert summary["k2"]["healthy"] is True

    def test_three_keys_first_two_bad_third_succeeds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # DeepSeek's audit-panel example: "2 keys with first 2 invalid,
        # 3rd succeeds, assert 3rd was used"
        monkeypatch.setenv("KIMI_API_KEY_1", "k1-bad-auth")
        monkeypatch.setenv("KIMI_API_KEY_2", "k2-bad-quota")
        monkeypatch.setenv("KIMI_API_KEY_3", "k3-good")

        engines_by_key = {
            "k1-bad-auth": _make_engine(
                success=False, error="401 Unauthorized",
            ),
            "k2-bad-quota": _make_engine(
                success=False, error="429 rate limit",
            ),
            "k3-good": _make_engine(success=True, text="finally"),
        }

        result = dispatch_with_pool(
            "kimi-via-claude",
            "test",
            engine_builder=lambda p, k: engines_by_key[k],
            strategy="priority",
            max_retries=3,
        )

        assert result.success is True
        assert result.winning_alias == "k3"
        assert result.response.text == "finally"
        assert len(result.attempts) == 3
        assert [a.alias for a in result.attempts] == ["k1", "k2", "k3"]
        assert result.attempts[0].category == "auth-failed"
        assert result.attempts[1].category == "quota-exceeded"
        assert result.attempts[2].category == "up"

    def test_all_keys_fail_returns_failure(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "bad-1")
        monkeypatch.setenv("KIMI_API_KEY_2", "bad-2")
        engines = {
            "bad-1": _make_engine(success=False, error="401"),
            "bad-2": _make_engine(success=False, error="401"),
        }
        result = dispatch_with_pool(
            "kimi-via-claude", "test",
            engine_builder=lambda p, k: engines[k],
            strategy="priority",
        )
        assert result.success is False
        assert result.winning_alias == ""
        assert len(result.attempts) == 2

    def test_transient_failure_does_not_failover(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Network/timeout = same-key-retry-later, not failover
        monkeypatch.setenv("KIMI_API_KEY_1", "k1")
        monkeypatch.setenv("KIMI_API_KEY_2", "k2")
        engines = {
            "k1": _make_engine(
                success=False, error="connection timeout after 90s",
            ),
            "k2": _make_engine(success=True, text="should-not-be-used"),
        }
        result = dispatch_with_pool(
            "kimi-via-claude", "test",
            engine_builder=lambda p, k: engines[k],
            strategy="priority",
        )
        # Single attempt, no failover
        assert len(result.attempts) == 1
        assert result.attempts[0].category == "transient"
        assert result.success is False

    def test_unhealthy_alias_skipped_at_pick_time(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pre-mark k1 as auth-failed in the ledger.  Without health-
        # aware picking, dispatch would pick k1 first.  With it, k1
        # is excluded BEFORE the engine is even built.
        monkeypatch.setenv("KIMI_API_KEY_1", "k1")
        monkeypatch.setenv("KIMI_API_KEY_2", "k2")
        record_outcome(
            "KIMI_API_KEY", "k1", "KIMI_API_KEY_1",
            "auth-failed", source="probe",
        )
        engines = {
            "k1": _make_engine(success=True, text="should-not-be-used"),
            "k2": _make_engine(success=True, text="hello-from-k2"),
        }
        result = dispatch_with_pool(
            "kimi-via-claude", "test",
            engine_builder=lambda p, k: engines[k],
        )
        # k1 was never even tried because the ledger said it's unhealthy
        assert result.success is True
        assert result.winning_alias == "k2"
        assert len(result.attempts) == 1
        assert result.attempts[0].alias == "k2"

    def test_no_keys_configured_returns_failure(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No env vars set for KIMI
        result = dispatch_with_pool(
            "kimi-via-claude", "test",
            engine_builder=lambda p, k: _make_engine(True),
        )
        assert result.success is False
        assert len(result.attempts) == 0

    def test_unknown_provider_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with pytest.raises(ValueError, match="does not support"):
            dispatch_with_pool(
                "bogus-engine", "test",
                engine_builder=lambda p, k: _make_engine(True),
            )

    def test_health_ledger_updated_on_success(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # After a successful dispatch, the alias should show "up" in
        # the health ledger so the dashboard reflects it
        monkeypatch.setenv("KIMI_API_KEY_1", "good")
        result = dispatch_with_pool(
            "kimi-via-claude", "test",
            engine_builder=lambda p, k: _make_engine(True, text="done"),
        )
        assert result.success is True
        summary = alias_status_summary("KIMI_API_KEY")
        assert summary["k1"]["category"] == "up"
        assert summary["k1"]["healthy"] is True
        assert summary["k1"]["source"] == "dispatch"

    def test_max_retries_caps_attempts(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 4 bad keys, max_retries=2 — only 2 attempts should be made
        for n in range(1, 5):
            monkeypatch.setenv(f"KIMI_API_KEY_{n}", f"bad-{n}")
        engines = {
            f"bad-{n}": _make_engine(success=False, error="401")
            for n in range(1, 5)
        }
        result = dispatch_with_pool(
            "kimi-via-claude", "test",
            engine_builder=lambda p, k: engines[k],
            strategy="priority",
            max_retries=2,
        )
        assert result.success is False
        assert len(result.attempts) == 2
        # k1 then k2, never k3 or k4
        assert [a.alias for a in result.attempts] == ["k1", "k2"]


class TestPoolDispatchRotation:
    """Verify rotation strategy actually rotates."""

    def test_rotation_uses_each_key_in_round_robin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "k1")
        monkeypatch.setenv("KIMI_API_KEY_2", "k2")
        monkeypatch.setenv("KIMI_API_KEY_3", "k3")
        # All succeed; rotation should cycle through them
        engines = {
            k: _make_engine(success=True, text=k) for k in ("k1", "k2", "k3")
        }
        reset_rotation_counter("KIMI_API_KEY")
        results = [
            dispatch_with_pool(
                "kimi-via-claude", "p",
                engine_builder=lambda p, k: engines[k],
                strategy="rotation",
            )
            for _ in range(6)
        ]
        winners = [r.winning_alias for r in results]
        assert winners == ["k1", "k2", "k3", "k1", "k2", "k3"]
