"""W14-KEYS-POOL 2026-05-26: tests for the generic multi-key resolver."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from harness.keys import (
    KeyEntry,
    discover_pool,
    list_provider_keys,
    mask_value,
    pick_next_key,
    resolve_keys,
)
from harness.keys.resolve import reset_rotation_counter


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with a clean slate for the providers we test."""
    for prefix in ("KIMI_API_KEY", "MIMO_API_KEY", "DEEPSEEK_API_KEY",
                   "ANTHROPIC_API_KEY", "FAKE_TEST_KEY"):
        monkeypatch.delenv(prefix, raising=False)
        for n in range(1, 6):
            monkeypatch.delenv(f"{prefix}_{n}", raising=False)
            monkeypatch.delenv(f"{prefix}_LABEL_{n}", raising=False)
    reset_rotation_counter()


# ---------------------------------------------------------------------------
# mask_value
# ---------------------------------------------------------------------------


class TestMaskValue:
    def test_short_fully_masked(self) -> None:
        assert mask_value("abc") == "***"

    def test_empty_value(self) -> None:
        assert mask_value("") == ""

    def test_long_shows_4_each_side(self) -> None:
        m = mask_value("sk-abcdef1234567890")
        assert m.startswith("sk-a")
        assert m.endswith("7890")


# ---------------------------------------------------------------------------
# discover_pool
# ---------------------------------------------------------------------------


class TestDiscoverPool:
    def test_empty_when_nothing_set(self) -> None:
        assert discover_pool("KIMI_API_KEY") == []

    def test_legacy_singular(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KIMI_API_KEY", "sk-legacy")
        pool = discover_pool("KIMI_API_KEY")
        assert len(pool) == 1
        assert pool[0].slot == 1
        assert pool[0].alias == "k1"
        assert pool[0].env_var == "KIMI_API_KEY"
        assert pool[0].value == "sk-legacy"
        assert pool[0].source == "env-legacy"

    def test_single_indexed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-slot1")
        pool = discover_pool("KIMI_API_KEY")
        assert len(pool) == 1
        assert pool[0].slot == 1
        assert pool[0].env_var == "KIMI_API_KEY_1"
        assert pool[0].source == "env"

    def test_multiple_indexed_slots(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        monkeypatch.setenv("KIMI_API_KEY_3", "sk-c")
        pool = discover_pool("KIMI_API_KEY")
        assert [e.slot for e in pool] == [1, 2, 3]
        assert [e.value for e in pool] == ["sk-a", "sk-b", "sk-c"]
        assert [e.alias for e in pool] == ["k1", "k2", "k3"]

    def test_indexed_shadows_legacy(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If any *_N is set, the bare PREFIX is NOT used as slot 1."""
        monkeypatch.setenv("KIMI_API_KEY", "sk-legacy")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-slot2")
        pool = discover_pool("KIMI_API_KEY")
        # slot 1 missing, slot 2 present → no slot 1 entry
        assert len(pool) == 1
        assert pool[0].slot == 2
        assert pool[0].value == "sk-slot2"
        # The legacy value is not silently demoted to slot 1
        assert "sk-legacy" not in [e.value for e in pool]

    def test_gaps_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Slot 1 missing + slot 3 present → just slot 3 returned."""
        monkeypatch.setenv("KIMI_API_KEY_3", "sk-only-3")
        pool = discover_pool("KIMI_API_KEY")
        assert len(pool) == 1
        assert pool[0].slot == 3

    def test_label_attached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-primary")
        monkeypatch.setenv("KIMI_API_KEY_LABEL_1", "primary")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-backup")
        monkeypatch.setenv("KIMI_API_KEY_LABEL_2", "backup-personal")
        pool = discover_pool("KIMI_API_KEY")
        assert pool[0].label == "primary"
        assert pool[1].label == "backup-personal"

    def test_max_slots_caps_search(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-1")
        monkeypatch.setenv("KIMI_API_KEY_5", "sk-5")
        pool = discover_pool("KIMI_API_KEY", max_slots=4)
        assert [e.slot for e in pool] == [1]  # slot 5 ignored

    def test_empty_prefix_returns_empty(self) -> None:
        assert discover_pool("") == []


# ---------------------------------------------------------------------------
# resolve_keys (backward-compat shim)
# ---------------------------------------------------------------------------


class TestResolveKeysCompat:
    def test_matches_proxy_api(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The old proxy resolver returned dict {"k1": v, "k2": v}
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        keys = resolve_keys("KIMI_API_KEY")
        assert keys == {"k1": "sk-a", "k2": "sk-b"}

    def test_legacy_still_works(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY", "sk-legacy")
        keys = resolve_keys("KIMI_API_KEY")
        assert keys == {"k1": "sk-legacy"}

    def test_default_prefix(self) -> None:
        # No keys set anywhere; default Kimi prefix returns empty dict
        # (matches old proxy behavior)
        keys = resolve_keys("KIMI_API_KEY")
        assert keys == {}


# ---------------------------------------------------------------------------
# list_provider_keys (UI-friendly)
# ---------------------------------------------------------------------------


class TestListProviderKeys:
    def test_shows_slot_1_when_empty(self) -> None:
        rows = list_provider_keys("KIMI_API_KEY")
        # Always render slot 1 even when nothing's set so the operator
        # has somewhere to paste
        assert len(rows) >= 1
        assert rows[0]["slot"] == 1
        assert rows[0]["has_value"] is False
        assert rows[0]["env_var"] == "KIMI_API_KEY_1"

    def test_shows_extra_empty_slot_when_populated(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        rows = list_provider_keys("KIMI_API_KEY")
        # Should show slot 1 (populated) + slot 2 (empty) so operator
        # can add another key without clicking +Add
        assert len(rows) == 2
        assert rows[0]["has_value"] is True
        assert rows[1]["has_value"] is False
        assert rows[1]["env_var"] == "KIMI_API_KEY_2"

    def test_no_raw_values_in_output(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-supersecret-1234")
        rows = list_provider_keys("KIMI_API_KEY")
        for row in rows:
            assert "sk-supersecret-1234" not in str(row)
            assert "value" not in row  # raw value not exposed

    def test_does_not_exceed_max_slots(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Even if 4 keys are set, list returns exactly 4 (no slot 5)
        for n in range(1, 5):
            monkeypatch.setenv(f"KIMI_API_KEY_{n}", f"sk-{n}")
        rows = list_provider_keys("KIMI_API_KEY", max_slots=4)
        assert len(rows) == 4
        assert rows[-1]["slot"] == 4

    def test_label_surfaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-1")
        monkeypatch.setenv("KIMI_API_KEY_LABEL_1", "production")
        rows = list_provider_keys("KIMI_API_KEY")
        assert rows[0]["label"] == "production"


# ---------------------------------------------------------------------------
# pick_next_key (rotation / priority / failover)
# ---------------------------------------------------------------------------


class TestPickNextKey:
    def test_none_when_pool_empty(self) -> None:
        assert pick_next_key("KIMI_API_KEY") is None

    def test_rotation_cycles(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        monkeypatch.setenv("KIMI_API_KEY_3", "sk-c")
        # Reset to make test deterministic
        reset_rotation_counter("KIMI_API_KEY")
        picked = [pick_next_key("KIMI_API_KEY").alias for _ in range(6)]
        assert picked == ["k1", "k2", "k3", "k1", "k2", "k3"]

    def test_rotation_respects_exclude(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        reset_rotation_counter("KIMI_API_KEY")
        # k1 is broken — rotation should land on k2 every time
        result = pick_next_key(
            "KIMI_API_KEY", exclude_aliases={"k1"},
        )
        assert result.alias == "k2"

    def test_priority_picks_lowest_available(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        result = pick_next_key("KIMI_API_KEY", strategy="priority")
        assert result.alias == "k1"

    def test_priority_falls_through_on_exclude(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        monkeypatch.setenv("KIMI_API_KEY_3", "sk-c")
        # Caller's retry loop appends failed aliases on each attempt
        result = pick_next_key(
            "KIMI_API_KEY", strategy="priority",
            exclude_aliases={"k1", "k2"},
        )
        assert result.alias == "k3"

    def test_failover_only_stays_on_k1(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        result = pick_next_key("KIMI_API_KEY", strategy="failover-only")
        assert result.alias == "k1"

    def test_failover_only_uses_k2_when_k1_excluded(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        result = pick_next_key(
            "KIMI_API_KEY", strategy="failover-only",
            exclude_aliases={"k1"},
        )
        assert result.alias == "k2"

    def test_pool_isolated_per_prefix(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Rotation counter for KIMI doesn't affect MIMO
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-k1")
        monkeypatch.setenv("MIMO_API_KEY_1", "tp-m1")
        monkeypatch.setenv("MIMO_API_KEY_2", "tp-m2")
        reset_rotation_counter()
        # Spin KIMI counter forward
        for _ in range(5):
            pick_next_key("KIMI_API_KEY")
        # MIMO rotation still starts at slot 1
        m = pick_next_key("MIMO_API_KEY")
        assert m.alias == "k1"


# ---------------------------------------------------------------------------
# Backward compatibility with v2 proxy
# ---------------------------------------------------------------------------


class TestProxyCompat:
    def test_proxy_resolve_keys_unchanged(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The proxy's resolve_keys() function should still work
        even after we migrate it to call into the generic resolver.
        (The proxy's own test suite covers this; this is a smoke
        test that the API surface stays identical.)"""
        from harness.proxy.app import resolve_keys as proxy_resolve_keys
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-a")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-b")
        result = proxy_resolve_keys("KIMI_API_KEY")
        assert result == {"k1": "sk-a", "k2": "sk-b"}
