"""Circuit-breaker state machine per API key."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from harness.proxy.state import CircuitState, KeyState


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

    return state


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
