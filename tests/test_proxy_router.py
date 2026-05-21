"""Tests for harness.proxy.router — key selection strategies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from harness.proxy.router import pick_key
from harness.proxy.state import KeyState, ProxyState


@pytest.fixture
def base_state() -> ProxyState:
    return ProxyState(
        started_at=datetime.now(timezone.utc).isoformat(),
        keys={
            "k1": KeyState(key_alias="k1", in_flight=0, avg_latency_ms=10.0),
            "k2": KeyState(key_alias="k2", in_flight=2, avg_latency_ms=5.0),
            "k3": KeyState(key_alias="k3", in_flight=1, avg_latency_ms=20.0),
        },
    )


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# least_loaded
# ---------------------------------------------------------------------------

def test_least_loaded_picks_lowest_in_flight(base_state: ProxyState, now: datetime) -> None:
    alias = pick_key(base_state, now=now, strategy="least_loaded")
    assert alias == "k1"


def test_least_loaded_tiebreaks_on_latency(base_state: ProxyState, now: datetime) -> None:
    base_state.keys["k1"].in_flight = 1
    alias = pick_key(base_state, now=now, strategy="least_loaded")
    # k1 and k3 both have in_flight=1; k1 has lower latency (10) than k3 (20)
    assert alias == "k1"


# ---------------------------------------------------------------------------
# round_robin
# ---------------------------------------------------------------------------

def test_round_robin_cycles_deterministically(base_state: ProxyState, now: datetime) -> None:
    # pool sorted by alias: k1, k2, k3
    base_state.total_requests = 0
    assert pick_key(base_state, now=now, strategy="round_robin") == "k1"
    base_state.total_requests = 1
    assert pick_key(base_state, now=now, strategy="round_robin") == "k2"
    base_state.total_requests = 2
    assert pick_key(base_state, now=now, strategy="round_robin") == "k3"
    base_state.total_requests = 3
    assert pick_key(base_state, now=now, strategy="round_robin") == "k1"


# ---------------------------------------------------------------------------
# random
# ---------------------------------------------------------------------------

def test_random_returns_valid_key(base_state: ProxyState, now: datetime) -> None:
    alias = pick_key(base_state, now=now, strategy="random")
    assert alias in {"k1", "k2", "k3"}


# ---------------------------------------------------------------------------
# saturation / empty pool
# ---------------------------------------------------------------------------

def test_none_when_pool_empty(now: datetime) -> None:
    state = ProxyState(started_at=datetime.now(timezone.utc).isoformat(), keys={})
    assert pick_key(state, now=now) is None


def test_none_when_all_at_max_concurrent(base_state: ProxyState, now: datetime) -> None:
    for k in base_state.keys.values():
        k.in_flight = k.max_concurrent
    assert pick_key(base_state, now=now) is None


def test_none_when_all_open(base_state: ProxyState, now: datetime) -> None:
    from harness.proxy.state import CircuitState
    for k in base_state.keys.values():
        k.circuit_state = CircuitState.OPEN
        k.cooldown_until = (now + timedelta(seconds=60)).isoformat()
    assert pick_key(base_state, now=now) is None
