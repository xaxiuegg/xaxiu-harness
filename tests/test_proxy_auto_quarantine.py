"""Tests for AUTO-QUARANTINE-KEY — circuit-flap auto-quarantines a key."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from harness.proxy.circuit import FLAP_THRESHOLD, FLAP_WINDOW_MINUTES, _detect_flap, transition
from harness.proxy.state import CircuitState, KeyState


def _trip_to_open(state: KeyState, now: datetime) -> KeyState:
    """Force 3 consecutive server_error outcomes to trip the breaker."""
    for _ in range(3):
        state = transition(state, "server_error", now=now)
    return state


def test_detect_flap_false_when_below_threshold() -> None:
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    state.circuit_trip_history = [
        (now - timedelta(minutes=10)).isoformat(),
        (now - timedelta(minutes=5)).isoformat(),
    ]
    assert _detect_flap(state, now) is False


def test_detect_flap_true_when_three_in_window() -> None:
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    state.circuit_trip_history = [
        (now - timedelta(minutes=30)).isoformat(),
        (now - timedelta(minutes=20)).isoformat(),
        (now - timedelta(minutes=10)).isoformat(),
    ]
    assert _detect_flap(state, now) is True


def test_detect_flap_false_when_old_trips_outside_window() -> None:
    """Trips older than FLAP_WINDOW_MINUTES don't count."""
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    state.circuit_trip_history = [
        (now - timedelta(minutes=120)).isoformat(),
        (now - timedelta(minutes=90)).isoformat(),
        (now - timedelta(minutes=80)).isoformat(),
    ]
    assert _detect_flap(state, now) is False


def test_first_trip_does_not_auto_quarantine() -> None:
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    state = _trip_to_open(state, now)
    assert state.circuit_state == CircuitState.OPEN
    assert state.permanent is False
    assert state.auto_quarantined_at is None
    assert len(state.circuit_trip_history) == 1


def test_three_trips_in_window_auto_quarantine() -> None:
    """Three consecutive trips ⇒ permanent quarantine."""
    base = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    # Trip 1
    state = _trip_to_open(state, base)
    # Reset consecutive_failures so the next 3 server_errors can trip again
    state.consecutive_failures = 0
    state.circuit_state = CircuitState.CLOSED
    # Trip 2 (15 min later)
    state = _trip_to_open(state, base + timedelta(minutes=15))
    state.consecutive_failures = 0
    state.circuit_state = CircuitState.CLOSED
    # Trip 3 (30 min later) ⇒ triggers auto-quarantine
    state = _trip_to_open(state, base + timedelta(minutes=30))
    assert state.permanent is True
    assert state.auto_quarantined_at is not None
    assert len(state.circuit_trip_history) == 3


def test_auto_quarantine_clears_cooldown_until() -> None:
    """Permanent quarantine implies no time-based recovery."""
    base = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    for i in range(3):
        state.consecutive_failures = 0
        state.circuit_state = CircuitState.CLOSED
        state = _trip_to_open(state, base + timedelta(minutes=15 * i))
    assert state.permanent is True
    assert state.cooldown_until is None


def test_trips_outside_window_do_not_quarantine() -> None:
    """Three trips at 90-min intervals don't fall within a 60-min window."""
    base = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    for i in range(3):
        state.consecutive_failures = 0
        state.circuit_state = CircuitState.CLOSED
        state = _trip_to_open(state, base + timedelta(minutes=90 * i))
    # The last call sees only 1 trip in its 60-min window (its own).
    assert state.permanent is False
    assert state.auto_quarantined_at is None


def test_flap_constants_match_spec() -> None:
    assert FLAP_THRESHOLD == 3
    assert FLAP_WINDOW_MINUTES == 60
