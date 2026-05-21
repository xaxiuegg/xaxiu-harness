"""Tests for harness.proxy.circuit — state machine and outcome classification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from harness.proxy.circuit import classify_outcome, is_routable, transition
from harness.proxy.state import CircuitState, KeyState


@pytest.fixture
def base_key() -> KeyState:
    return KeyState(key_alias="k1")


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# classify_outcome
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("status", "exc", "expected"),
    [
        (200, None, "success"),
        (201, None, "success"),
        (401, None, "auth_failure"),
        (403, None, "auth_failure"),
        (429, None, "rate_limit"),
        (500, None, "server_error"),
        (502, None, "server_error"),
        (422, None, "schema_violation"),
        (418, None, "refusal"),
        (None, TimeoutError(), "timeout"),
        (None, httpx.ReadTimeout("", request=None), "timeout"),
        (None, httpx.ConnectTimeout("", request=None), "timeout"),
        (None, ConnectionError(), "server_error"),
    ],
)
def test_classify_outcome(status, exc, expected) -> None:
    assert classify_outcome(status, exc) == expected


# ---------------------------------------------------------------------------
# transition — success
# ---------------------------------------------------------------------------

def test_success_closed_stays_closed(base_key: KeyState, now: datetime) -> None:
    transition(base_key, "success", now=now)
    assert base_key.circuit_state == CircuitState.CLOSED
    assert base_key.consecutive_failures == 0


def test_success_half_open_to_closed(base_key: KeyState, now: datetime) -> None:
    base_key.circuit_state = CircuitState.HALF_OPEN
    transition(base_key, "success", now=now)
    assert base_key.circuit_state == CircuitState.CLOSED
    assert base_key.cooldown_until is None


# ---------------------------------------------------------------------------
# transition — non-tripping outcomes
# ---------------------------------------------------------------------------

def test_schema_violation_no_trip(base_key: KeyState, now: datetime) -> None:
    transition(base_key, "schema_violation", now=now)
    assert base_key.circuit_state == CircuitState.CLOSED
    assert base_key.consecutive_failures == 0


def test_refusal_no_trip(base_key: KeyState, now: datetime) -> None:
    transition(base_key, "refusal", now=now)
    assert base_key.circuit_state == CircuitState.CLOSED
    assert base_key.consecutive_failures == 0


# ---------------------------------------------------------------------------
# transition — failure accumulation
# ---------------------------------------------------------------------------

def test_three_failures_opens_circuit(base_key: KeyState, now: datetime) -> None:
    for _ in range(3):
        transition(base_key, "server_error", now=now)
    assert base_key.circuit_state == CircuitState.OPEN
    assert base_key.cooldown_until is not None


def test_auth_failure_permanently_opens(base_key: KeyState, now: datetime) -> None:
    transition(base_key, "auth_failure", now=now)
    assert base_key.circuit_state == CircuitState.OPEN
    assert base_key.permanent is True
    assert base_key.cooldown_until is None


# ---------------------------------------------------------------------------
# transition — cooldown durations
# ---------------------------------------------------------------------------

def test_rate_limit_cooldown_60s(base_key: KeyState, now: datetime) -> None:
    for _ in range(3):
        transition(base_key, "rate_limit", now=now)
    expected = (now + timedelta(seconds=60)).isoformat()
    assert base_key.cooldown_until == expected


def test_timeout_cooldown_60s(base_key: KeyState, now: datetime) -> None:
    for _ in range(3):
        transition(base_key, "timeout", now=now)
    expected = (now + timedelta(seconds=60)).isoformat()
    assert base_key.cooldown_until == expected


def test_server_error_cooldown_30s(base_key: KeyState, now: datetime) -> None:
    for _ in range(3):
        transition(base_key, "server_error", now=now)
    expected = (now + timedelta(seconds=30)).isoformat()
    assert base_key.cooldown_until == expected


# ---------------------------------------------------------------------------
# is_routable
# ---------------------------------------------------------------------------

def test_is_routable_closed_always_true(base_key: KeyState, now: datetime) -> None:
    assert is_routable(base_key, now=now) is True


def test_is_routable_open_transitions_half_open(base_key: KeyState, now: datetime) -> None:
    base_key.circuit_state = CircuitState.OPEN
    base_key.cooldown_until = (now - timedelta(seconds=1)).isoformat()
    assert is_routable(base_key, now=now) is True
    assert base_key.circuit_state == CircuitState.HALF_OPEN


def test_is_routable_half_open_only_when_idle(base_key: KeyState, now: datetime) -> None:
    base_key.circuit_state = CircuitState.HALF_OPEN
    base_key.in_flight = 1
    assert is_routable(base_key, now=now) is False
    base_key.in_flight = 0
    assert is_routable(base_key, now=now) is True


def test_is_routable_permanent_open_stays_false(base_key: KeyState, now: datetime) -> None:
    base_key.circuit_state = CircuitState.OPEN
    base_key.permanent = True
    assert is_routable(base_key, now=now) is False


def test_is_routable_open_cooldown_not_expired(base_key: KeyState, now: datetime) -> None:
    base_key.circuit_state = CircuitState.OPEN
    base_key.cooldown_until = (now + timedelta(seconds=30)).isoformat()
    assert is_routable(base_key, now=now) is False
