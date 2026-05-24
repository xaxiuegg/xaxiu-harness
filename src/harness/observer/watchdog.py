"""W11-OBSERVER-WATCHDOG-RECOVERY: self-recovery for the observer.

Per readiness panel: if the observer scheduler-status itself fails the
operator has no next step.  Add a watchdog-of-the-watchdog:

  - is_stale(state, now)        — detection primitive
  - stale_seconds(state, now)   — for dashboard timing
  - watchdog_status(...)        — structured status dict (JSON-friendly)
  - dashboard_banner(...)       — single-line text for the UI banner
  - restart_observer(...)       — unregister + re-register at SAME cadence
  - _register_for_platform()    — Windows Task Scheduler OR cron

Stale threshold: 2x the configured cadence_minutes since last_cycle_at.
Generous enough to absorb genuine slow cycles; tight enough that an
operator notices a multi-hour silence within one cadence period.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness.observer import cron_scheduler, state as observer_state

STALE_MULTIPLIER = 2  # last_cycle_at older than cadence_minutes * 2 = stale


def is_stale(state: observer_state.ObserverState,
             now: datetime | None = None) -> bool:
    """Return True if the observer hasn't fired in a suspicious amount of time.

    Returns False when:
      - observer is paused or disarmed (intentional silence)
      - no last_cycle_at yet (fresh observer; give it time)
      - last_cycle_at is malformed (no signal, don't false-alarm)
    """
    if not state.armed or state.paused:
        return False
    if state.last_cycle_at is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(state.last_cycle_at)
    except (ValueError, TypeError):
        return False
    # Normalize: naive → assume UTC
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (now - last).total_seconds()
    threshold = state.cadence_minutes * 60 * STALE_MULTIPLIER
    return elapsed > threshold


def stale_seconds(state: observer_state.ObserverState,
                  now: datetime | None = None) -> float | None:
    """Return seconds since last cycle, or None if no cycle yet.

    Note: returns the raw elapsed seconds — does NOT mean "stale".
    Use is_stale() for the boolean signal.
    """
    if state.last_cycle_at is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(state.last_cycle_at)
    except (ValueError, TypeError):
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last).total_seconds()


def _humanize_seconds(secs: float) -> str:
    """Format duration in operator-friendly units."""
    if secs < 60:
        return f"{int(secs)}s"
    if secs < 3600:
        return f"{int(secs // 60)}min"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    return f"{int(secs // 86400)}d"


def watchdog_status(observer_dir: Path | None = None) -> dict:
    """Return a structured status dict for the dashboard + agent SDK.

    Shape:
        {
            "is_stale": bool,
            "last_cycle_at": str | None,
            "stale_seconds": float | None,
            "stale_human": str,        # W12 add: "20min ago" / "(never)"
            "cadence_minutes": int,
            "cadence_human": str,      # W12 add: "every 60m"
            "armed": bool,
            "paused": bool,
            "verdict": str,            # W12 add: "OK" | "STALE" | "PAUSED" | "DISARMED" | "UNINITIALIZED"
            "summary_line": str,       # W12 add: one-line operator-friendly summary
            "suggested_action": str | None,  # human text or None if healthy
        }

    W12-WATCHDOG-HUMAN-FORMAT (2026-05-24): added stale_human +
    cadence_human + verdict + summary_line per 20-agent panel finding
    M07: 'machine-shaped output `stale_seconds: 1209.651516` with no
    context'.  Now matches the cost-widget pattern with a one-liner.
    """
    try:
        state = observer_state.read_state(observer_dir=observer_dir)
    except Exception:
        # Corrupt state file = degenerate case; report as unhealthy
        # but with a different action.
        return {
            "is_stale": True,
            "last_cycle_at": None,
            "stale_seconds": None,
            "stale_human": "(state file unreadable)",
            "cadence_minutes": 60,
            "cadence_human": "every 60m (default)",
            "armed": False,
            "paused": False,
            "verdict": "CORRUPT",
            "summary_line": (
                "Watchdog: CORRUPT - observer state file unreadable"
            ),
            "suggested_action": (
                "observer state file unreadable - run "
                "`harness observer reset` to rebuild"
            ),
        }
    now = datetime.now(timezone.utc)
    stale = is_stale(state, now=now)
    elapsed = stale_seconds(state, now=now)
    elapsed_human = (
        f"{_humanize_seconds(elapsed)} ago" if elapsed is not None
        else "(never)"
    )
    cadence_human = f"every {state.cadence_minutes}m"
    # W12-WATCHDOG-HUMAN-FORMAT: verdict + summary_line per panel M07
    if not state.armed:
        verdict = "DISARMED"
        summary = f"Watchdog: DISARMED - observer disarmed (last cycle {elapsed_human})"
    elif state.paused:
        verdict = "PAUSED"
        summary = f"Watchdog: PAUSED - operator paused (last cycle {elapsed_human})"
    elif state.last_cycle_at is None:
        verdict = "UNINITIALIZED"
        summary = f"Watchdog: UNINITIALIZED - observer armed but no cycles yet (cadence: {cadence_human})"
    elif stale:
        verdict = "STALE"
        summary = (
            f"Watchdog: STALE - last cycle {elapsed_human} (expected: {cadence_human})"
        )
    else:
        verdict = "OK"
        summary = f"Watchdog: OK - last cycle {elapsed_human} (cadence: {cadence_human})"

    action: str | None = None
    if stale:
        action = (
            f"observer last fired {elapsed_human} - run "
            f"`harness observer restart` to re-arm the scheduler"
        )
    return {
        "is_stale": stale,
        "last_cycle_at": state.last_cycle_at,
        "stale_seconds": elapsed,
        "stale_human": elapsed_human,
        "cadence_minutes": state.cadence_minutes,
        "cadence_human": cadence_human,
        "armed": state.armed,
        "paused": state.paused,
        "verdict": verdict,
        "summary_line": summary,
        "suggested_action": action,
    }


def dashboard_banner(observer_dir: Path | None = None) -> str | None:
    """Single-line banner text for the dashboard UI.  None when healthy."""
    status = watchdog_status(observer_dir=observer_dir)
    if not status["is_stale"]:
        return None
    elapsed = status["stale_seconds"]
    elapsed_human = _humanize_seconds(elapsed) if elapsed else "a while"
    return (
        f"Observer task last fired {elapsed_human} ago — "
        f"click to restart the scheduler"
    )


# -- restart primitive --------------------------------------------------


def _unregister_for_platform() -> tuple[bool, str]:
    """Unregister observer tasks on the current platform."""
    if cron_scheduler.is_unix_like():
        return cron_scheduler.unregister_cron_tasks()
    from harness.observer import scheduler as ts
    return ts.unregister_tasks()


def _register_for_platform(cadence_minutes: int = 60,
                            daily_time: str = "23:00",
                            include_chat: bool = True) -> tuple[bool, str]:
    """Register observer tasks on the current platform."""
    if cron_scheduler.is_unix_like():
        return cron_scheduler.register_cron_tasks(
            cadence_minutes=cadence_minutes,
            daily_time=daily_time,
            include_chat=include_chat,
        )
    from harness.observer import scheduler as ts
    return ts.register_tasks(
        cadence_minutes=cadence_minutes,
        daily_time=daily_time,
        include_chat=include_chat,
    )


def restart_observer(observer_dir: Path | None = None) -> tuple[bool, str]:
    """Restart the observer scheduler at the SAME cadence as before.

    Reads existing cadence_minutes + daily_retro_time from observer state,
    calls unregister (best effort), then register.  Returns (ok, message).

    W11-L5-OUTPUT-CONTRACT: records the outcome via
    l5_escalation.record_restart_outcome.  On the 3rd consecutive
    failure (or beyond), the returned message PREPENDS a visible L5
    ESCALATION banner so the operator sees the severity immediately
    instead of just another "(ok=False, msg=...)" return.

    Used by:
      - `harness observer restart` CLI verb
      - the dashboard banner's click-to-restart link
      - the agent's harness SDK (auto-recovery)
    """
    from harness import l5_escalation

    try:
        state = observer_state.read_state(observer_dir=observer_dir)
    except Exception as exc:
        return False, f"could not read observer state: {exc}"

    # Best-effort unregister — proceed even if it fails (task may
    # have been removed already, etc).
    _unregister_for_platform()

    ok, msg = _register_for_platform(
        cadence_minutes=state.cadence_minutes,
        daily_time=state.daily_retro_time,
        include_chat=True,
    )
    # Persist outcome + read back the consecutive-failure count.  Wrap
    # in try/except so a state-write failure doesn't mask the original
    # restart success/failure that the caller cares about.
    try:
        failure_count = l5_escalation.record_restart_outcome(
            ok, observer_dir=observer_dir,
        )
    except Exception:
        failure_count = 0

    if not ok:
        base_msg = f"restart failed during register: {msg}"
        if l5_escalation.should_escalate_to_l5(failure_count):
            banner = l5_escalation.render_l5_banner(
                code="L5.observer.OBSERVER_RESTART_LOOP",
                summary=(
                    f"observer scheduler restart failed "
                    f"{failure_count} consecutive times — "
                    f"the watchdog cannot self-recover"
                ),
                action=(
                    "Inspect scheduler manually: on Windows run "
                    "`Get-ScheduledTask -TaskName XaxiuHarnessObserver*`; "
                    "on Linux/Mac run `crontab -l | grep HARNESS_OBSERVER`. "
                    "Then run `harness observer install-scheduler` with "
                    "elevated privileges if needed."
                ),
                evidence=[
                    f"latest register message: {msg}",
                    f"cadence: every {state.cadence_minutes} min",
                    f"daily retro at: {state.daily_retro_time}",
                ],
            )
            return False, banner + "\n" + base_msg
        return False, base_msg
    return True, f"observer restarted: {msg}"
