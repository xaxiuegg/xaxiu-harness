"""Circuit-breaker state machine per API key."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from harness.proxy.state import CircuitState, KeyState


# AUTO-QUARANTINE-KEY (2026-05-21): 3+ circuit trips inside this window
# auto-quarantines the key.  Tunable here so a future operator config knob
# can override.
FLAP_WINDOW_MINUTES = 60
FLAP_THRESHOLD = 3


def _detect_flap(state: KeyState, now: datetime) -> bool:
    """Return True if ``state.circuit_trip_history`` shows ≥FLAP_THRESHOLD trips
    within the last FLAP_WINDOW_MINUTES."""
    if len(state.circuit_trip_history) < FLAP_THRESHOLD:
        return False
    window_start = now - timedelta(minutes=FLAP_WINDOW_MINUTES)
    in_window = 0
    for ts in state.circuit_trip_history:
        try:
            t = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if t >= window_start:
            in_window += 1
    return in_window >= FLAP_THRESHOLD


def classify_outcome(http_status: int | None, exception: Exception | None) -> str:
    """Map an HTTP response or exception to an outcome label."""
    if exception is not None:
        exc_name = type(exception).__name__
        if exc_name in (
            "TimeoutError",
            "ReadTimeout",
            "ConnectTimeout",
            "asyncio.TimeoutError",
        ):
            return "timeout"
        return "server_error"
    if http_status is None:
        return "server_error"
    if http_status in (401, 403):
        return "auth_failure"
    if http_status == 429:
        return "rate_limit"
    if 500 <= http_status < 600:
        return "server_error"
    if 200 <= http_status < 300:
        return "success"
    if http_status == 422:
        return "schema_violation"
    if 400 <= http_status < 500:
        return "refusal"
    return "server_error"


def _now_str(now: datetime) -> str:
    return now.isoformat()


def transition(state: KeyState, outcome: str, *, now: datetime) -> KeyState:
    """Mutate *state* according to the circuit-breaker rules and return it."""
    state.recent_outcomes.append(outcome)
    if len(state.recent_outcomes) > 20:
        state.recent_outcomes = state.recent_outcomes[-20:]

    state.last_used_at = _now_str(now)

    if outcome == "success":
        state.consecutive_failures = 0
        state.total_dispatched += 1
        if state.circuit_state == CircuitState.HALF_OPEN:
            state.circuit_state = CircuitState.CLOSED
            state.cooldown_until = None
        return state

    if outcome in ("schema_violation", "refusal"):
        state.total_dispatched += 1
        return state

    # Failure outcomes that may trip the breaker
    state.consecutive_failures += 1
    state.total_failed += 1
    state.total_dispatched += 1

    if outcome == "auth_failure":
        state.circuit_state = CircuitState.OPEN
        state.permanent = True
        state.cooldown_until = None
        return state

    if state.consecutive_failures >= 3:
        state.circuit_state = CircuitState.OPEN
        if outcome == "rate_limit":
            cooldown = timedelta(seconds=60)
        elif outcome == "timeout":
            cooldown = timedelta(seconds=60)
        elif outcome == "server_error":
            cooldown = timedelta(seconds=30)
        else:
            cooldown = timedelta(seconds=30)
        state.cooldown_until = _now_str(now + cooldown)
        # AUTO-QUARANTINE-KEY: record this trip + check for flap
        state.circuit_trip_history.append(_now_str(now))
        if len(state.circuit_trip_history) > 20:
            state.circuit_trip_history = state.circuit_trip_history[-20:]
        if _detect_flap(state, now) and not state.permanent:
            state.permanent = True
            state.auto_quarantined_at = _now_str(now)
            # Clear cooldown — permanent quarantine doesn't recover on time
            state.cooldown_until = None
            # WIRE-FLAP-ESCALATION (2026-05-21): write an L4 escalation
            # file so the operator sees the auto-quarantine event in
            # `harness loop status` / dashboard.  Best-effort I/O.
            _write_flap_escalation(state.key_alias, now)

    return state


def _write_flap_escalation(key_alias: str, now: datetime) -> None:
    """Append an L4 escalation record to coord/observer/escalations/.

    Best-effort — never raises.  The file format mirrors what
    `harness loop status` reads, so flap events surface in the same
    panel as observer + session-handoff flags.
    """
    try:
        from pathlib import Path
        import json
        esc_dir = Path("coord") / "observer" / "escalations"
        esc_dir.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%dT%H%M%S")
        record = {
            "level": "L4",
            "tag": "proxy_flap_quarantine",
            "code": "E_PROXY_AUTO_QUARANTINE",
            "key_alias": key_alias,
            "at": _now_str(now),
            "diagnostic": (
                f"Proxy key '{key_alias}' tripped circuit ≥3 times within "
                f"{FLAP_WINDOW_MINUTES}min — auto-quarantined.  "
                f"Investigate root cause, then `harness proxy reset-circuit {key_alias}`."
            ),
        }
        path = esc_dir / f"flap_{key_alias}_{ts}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    except Exception:
        pass


def is_routable(state: KeyState, *, now: datetime) -> bool:
    """Return whether *state* may accept a new request (mutates OPEN→HALF_OPEN when cooldown expires)."""
    if state.circuit_state == CircuitState.CLOSED:
        return True
    if state.circuit_state == CircuitState.HALF_OPEN:
        return state.in_flight == 0
    if state.circuit_state == CircuitState.OPEN:
        if state.permanent:
            return False
        if state.cooldown_until is not None:
            cooldown_dt = datetime.fromisoformat(state.cooldown_until)
            if now >= cooldown_dt:
                state.circuit_state = CircuitState.HALF_OPEN
                state.cooldown_until = None
                return state.in_flight == 0
        return False
    return False
