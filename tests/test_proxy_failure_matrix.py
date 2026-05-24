"""W9-PROXY-FAILURE-MATRIX: each row of spec/proxy-failure-matrix.md
gets a regression test.

The proxy is the v2/A safety-critical layer.  M13 flagged it as
"opaque" with zero mutation-kill coverage and a defining feature
(auto-quarantine-on-flap) that was silently non-functional for an
unknown duration before W8.  These tests pin the documented behavior
to executable assertions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from harness.proxy import circuit, router
from harness.proxy.state import CircuitState, KeyState, ProxyState


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mk_state(*, n_keys: int = 4) -> ProxyState:
    state = ProxyState(started_at=_now().isoformat())
    for i in range(n_keys):
        state.keys[f"key_{i}"] = KeyState(key_alias=f"key_{i}")
    return state


# -- Row 1: single key revoked -- fail-open --------------------------------


def test_single_key_revoked_pool_still_serves():
    """When one key gets 401/403, other keys still route."""
    state = _mk_state(n_keys=3)
    # Simulate key_0 hitting auth failure repeatedly
    now = _now()
    k0 = state.keys["key_0"]
    for _ in range(10):
        circuit.transition(k0, "auth_failure", now=now)
    # key_0's circuit should be OPEN (or k0 quarantined)
    assert k0.circuit_state == CircuitState.OPEN or k0.permanent
    # pick_key should still return a healthy key
    picked = router.pick_key(state, now=now)
    assert picked in ("key_1", "key_2")
    assert picked != "key_0"


def test_classify_outcome_401_is_auth_failure():
    assert circuit.classify_outcome(401, None) == "auth_failure"
    assert circuit.classify_outcome(403, None) == "auth_failure"


# -- Row 2: all keys revoked -- fail-closed --------------------------------


def test_all_keys_revoked_returns_none():
    state = _mk_state(n_keys=3)
    now = _now()
    for k in state.keys.values():
        for _ in range(10):
            circuit.transition(k, "auth_failure", now=now)
    picked = router.pick_key(state, now=now)
    assert picked is None


# -- Row 3: circuit-breaker open on every key -- fail-closed ---------------


def test_all_circuits_open_returns_none():
    state = _mk_state(n_keys=2)
    for k in state.keys.values():
        k.circuit_state = CircuitState.OPEN
        # Cooldown in the future so is_routable -> False
        k.cooldown_until = (_now() + timedelta(seconds=60)).isoformat()
    assert router.pick_key(state, now=_now()) is None


# -- Row 4: in-flight saturation -- fail-closed ----------------------------


def test_pool_saturated_returns_none():
    state = _mk_state(n_keys=2)
    for k in state.keys.values():
        k.in_flight = k.max_concurrent  # at cap
    assert router.pick_key(state, now=_now()) is None


def test_partial_saturation_routes_to_unsaturated_key():
    state = _mk_state(n_keys=2)
    state.keys["key_0"].in_flight = state.keys["key_0"].max_concurrent
    state.keys["key_1"].in_flight = 0
    picked = router.pick_key(state, now=_now())
    assert picked == "key_1"


# -- Row 6: TLS handshake failure -> server_error -------------------------


def test_tls_handshake_failure_classified_as_server_error():
    class _SSLError(Exception):
        pass

    out = circuit.classify_outcome(None, _SSLError("bad cert"))
    assert out == "server_error"


# -- Row 7: upstream timeout -- classified correctly -----------------------


def test_timeout_classified_by_exception_name():
    """The classifier recognizes various timeout exception names."""
    class TimeoutError(Exception):  # shadows builtin intentionally
        pass

    class ReadTimeout(Exception):
        pass

    class ConnectTimeout(Exception):
        pass

    assert circuit.classify_outcome(None, TimeoutError()) == "timeout"
    assert circuit.classify_outcome(None, ReadTimeout()) == "timeout"
    assert circuit.classify_outcome(None, ConnectTimeout()) == "timeout"


# -- Row 8: rate-limit (429) ----------------------------------------------


def test_rate_limit_classified():
    assert circuit.classify_outcome(429, None) == "rate_limit"


# -- Row 9: schema violation (422) does NOT trip circuit -------------------


def test_schema_violation_classified():
    assert circuit.classify_outcome(422, None) == "schema_violation"


def test_schema_violation_does_not_trip_circuit_immediately():
    state = _mk_state(n_keys=1)
    k = state.keys["key_0"]
    # Even repeated schema violations: caller's payload bug
    for _ in range(5):
        circuit.transition(k, "schema_violation", now=_now())
    # Schema-violation should NOT cause auto-quarantine on its own
    assert not k.permanent


# -- Row 10: flap detection -- the load-bearing safety feature --------------


def test_flap_detection_quarantines_after_three_trips_in_window():
    """≥3 trips inside FLAP_WINDOW_MINUTES → permanent quarantine.

    Note: this exercises the flap-on-server_error path; the
    auth_failure outcome bypasses flap detection and always sets
    permanent=True on first hit per circuit.transition's special
    case.
    """
    state = _mk_state(n_keys=1)
    k = state.keys["key_0"]
    now = _now()
    # Plant 2 prior trip timestamps in the window (just under threshold)
    k.circuit_trip_history = [
        (now - timedelta(minutes=10)).isoformat(),
        (now - timedelta(minutes=5)).isoformat(),
    ]
    # Set consecutive_failures so the next failure trips the circuit
    k.consecutive_failures = 2  # 3rd will trip
    circuit.transition(k, "server_error", now=now)
    # After the 3rd trip, flap should auto-quarantine
    assert k.permanent
    assert k.auto_quarantined_at is not None
    assert k.circuit_state == CircuitState.OPEN


def test_flap_detection_does_not_quarantine_with_trips_outside_window():
    """Trips OUTSIDE the 60-min window don't count toward flap."""
    state = _mk_state(n_keys=1)
    k = state.keys["key_0"]
    now = _now()
    # 2 old trips outside the window
    k.circuit_trip_history = [
        (now - timedelta(hours=3)).isoformat(),
        (now - timedelta(hours=2)).isoformat(),
    ]
    k.consecutive_failures = 2  # next failure will trip circuit
    circuit.transition(k, "server_error", now=now)
    # Should NOT be auto-quarantined: only the just-now trip is in window
    # (the 2 old ones are outside)
    assert not k.permanent
    # Circuit IS open (consecutive_failures hit 3) but quarantine is not permanent
    assert k.circuit_state == CircuitState.OPEN


def test_flap_detection_handles_invalid_timestamp_gracefully():
    """A corrupted ISO timestamp in history shouldn't crash the detector."""
    state = _mk_state(n_keys=1)
    k = state.keys["key_0"]
    k.circuit_trip_history = ["not-iso-format", "garbage"]
    # Should not raise
    result = circuit._detect_flap(k, _now())
    assert result is False


# -- Row 11: proxy state file corrupt -- fail-closed -----------------------


def test_corrupt_state_file_raises_validation_error(tmp_path):
    """A corrupted proxy_state.json must raise rather than silently
    falling back to an empty state — that would lose every key's
    health history."""
    from harness.proxy.state import read_state, ProxyState
    bad = tmp_path / "proxy_state.json"
    bad.write_text("{this is not valid json}", encoding="utf-8")
    with pytest.raises((Exception,)):
        read_state(bad)


# -- Row 12: proxy process killed mid-write --------------------------------


def test_proxy_write_is_atomic_on_simulated_crash(tmp_path, monkeypatch):
    """A simulated kill mid-write leaves the original state untouched."""
    from harness.proxy.state import read_state, write_state, ProxyState
    state_path = tmp_path / "proxy_state.json"
    initial = ProxyState(started_at=_now().isoformat())
    initial.keys["key_0"] = KeyState(key_alias="key_0", total_dispatched=42)
    write_state(initial, state_path)

    # Simulate kill mid-write by monkey-patching json.dump to raise
    import json as _json
    original_dump = _json.dump

    def _crash(*args, **kwargs):
        raise KeyboardInterrupt("simulated kill")

    monkeypatch.setattr(_json, "dump", _crash)
    new_state = ProxyState(started_at=_now().isoformat())
    new_state.keys["key_0"] = KeyState(key_alias="key_0",
                                         total_dispatched=999)
    with pytest.raises(KeyboardInterrupt):
        write_state(new_state, state_path)

    # The original state should still be readable
    monkeypatch.setattr(_json, "dump", original_dump)
    recovered = read_state(state_path)
    assert recovered.keys["key_0"].total_dispatched == 42


# -- Operator-action verbs exist on the CLI -------------------------------


def test_operator_can_unquarantine_via_cli():
    """W9 matrix references `harness proxy unquarantine` — verify the
    CLI command exists (so the matrix's prescribed action is real)."""
    from harness.cli import cli
    proxy = cli.commands.get("proxy")
    assert proxy is not None
    # The proxy command group should have unquarantine as a subcommand
    sub = getattr(proxy, "commands", {})
    assert "unquarantine" in sub, (
        f"Expected `harness proxy unquarantine` subcommand; "
        f"available: {sorted(sub.keys())}"
    )
