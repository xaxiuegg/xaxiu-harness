"""W11-OBSERVER-WATCHDOG-RECOVERY: tests for observer self-recovery.

Per readiness panel: if the observer scheduler-status itself fails
the operator has no next step.  Add watchdog-of-the-watchdog:
- detect stale observer (last_cycle_at > 2x cadence ago)
- expose harness observer watchdog-status verb
- expose harness observer restart verb (unregister + re-register)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from harness.observer import state as observer_state
from harness.observer import watchdog


# -- detection helpers ---------------------------------------------------


def test_is_stale_returns_false_when_no_cycle_yet():
    """A fresh observer with no cycles yet is NOT stale — give it time."""
    s = observer_state.ObserverState(armed=True, cadence_minutes=60,
                                       last_cycle_at=None)
    assert watchdog.is_stale(s, now=datetime.now(timezone.utc)) is False


def test_is_stale_returns_false_when_recently_fired():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=30)).isoformat()
    s = observer_state.ObserverState(armed=True, cadence_minutes=60,
                                       last_cycle_at=last)
    assert watchdog.is_stale(s, now=now) is False


def test_is_stale_returns_true_when_2x_cadence_elapsed():
    """Stale threshold: 2x cadence_minutes since last cycle."""
    now = datetime.now(timezone.utc)
    # 2.5x cadence ago → stale
    last = (now - timedelta(minutes=150)).isoformat()
    s = observer_state.ObserverState(armed=True, cadence_minutes=60,
                                       last_cycle_at=last)
    assert watchdog.is_stale(s, now=now) is True


def test_is_stale_returns_false_when_paused():
    """Paused observer is not "stale" — it's intentionally idle."""
    now = datetime.now(timezone.utc)
    last = (now - timedelta(hours=10)).isoformat()
    s = observer_state.ObserverState(
        armed=True, paused=True, cadence_minutes=60, last_cycle_at=last,
    )
    assert watchdog.is_stale(s, now=now) is False


def test_is_stale_returns_false_when_disarmed():
    """Disarmed observer also doesn't get the stale flag."""
    now = datetime.now(timezone.utc)
    last = (now - timedelta(hours=10)).isoformat()
    s = observer_state.ObserverState(
        armed=False, cadence_minutes=60, last_cycle_at=last,
    )
    assert watchdog.is_stale(s, now=now) is False


def test_is_stale_handles_malformed_timestamp_gracefully():
    """A garbage timestamp should not crash — return False (no signal)."""
    s = observer_state.ObserverState(
        armed=True, cadence_minutes=60, last_cycle_at="not-a-timestamp",
    )
    assert watchdog.is_stale(s, now=datetime.now(timezone.utc)) is False


# -- stale_seconds (used by the dashboard banner) -----------------------


def test_stale_seconds_returns_none_when_no_cycle_yet():
    s = observer_state.ObserverState(armed=True, last_cycle_at=None)
    assert watchdog.stale_seconds(s, now=datetime.now(timezone.utc)) is None


def test_stale_seconds_returns_zero_when_just_fired():
    now = datetime.now(timezone.utc)
    s = observer_state.ObserverState(armed=True, last_cycle_at=now.isoformat())
    # Within tolerance of 0
    assert abs(watchdog.stale_seconds(s, now=now)) < 1.0


def test_stale_seconds_returns_positive_when_lagging():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=180)).isoformat()
    s = observer_state.ObserverState(armed=True, cadence_minutes=60,
                                       last_cycle_at=last)
    secs = watchdog.stale_seconds(s, now=now)
    assert secs is not None
    # 180 min = 10800 s, within tolerance
    assert 10700 < secs < 10900


# -- watchdog_status (the public API surface) ---------------------------


def test_watchdog_status_returns_required_keys(tmp_path):
    """Shape contract: must include is_stale, last_cycle_at, stale_seconds,
    suggested_action."""
    s = observer_state.ObserverState(armed=True, cadence_minutes=60)
    observer_state.write_state(s, observer_dir=tmp_path)
    status = watchdog.watchdog_status(observer_dir=tmp_path)
    required = {"is_stale", "last_cycle_at", "stale_seconds",
                "suggested_action", "cadence_minutes", "armed", "paused"}
    assert required <= set(status.keys()), (
        f"missing keys: {required - set(status.keys())}"
    )


def test_watchdog_status_suggested_action_is_none_when_healthy(tmp_path):
    now = datetime.now(timezone.utc)
    s = observer_state.ObserverState(
        armed=True, cadence_minutes=60, last_cycle_at=now.isoformat(),
    )
    observer_state.write_state(s, observer_dir=tmp_path)
    status = watchdog.watchdog_status(observer_dir=tmp_path)
    assert status["suggested_action"] is None
    assert status["is_stale"] is False


def test_watchdog_status_suggested_action_when_stale(tmp_path):
    now = datetime.now(timezone.utc)
    last = (now - timedelta(hours=5)).isoformat()
    s = observer_state.ObserverState(
        armed=True, cadence_minutes=60, last_cycle_at=last,
    )
    observer_state.write_state(s, observer_dir=tmp_path)
    status = watchdog.watchdog_status(observer_dir=tmp_path)
    assert status["is_stale"] is True
    # Suggested action mentions restart
    assert status["suggested_action"] is not None
    assert "restart" in status["suggested_action"].lower()


def test_watchdog_status_handles_missing_state_file(tmp_path):
    """When observer-state.json doesn't exist yet, return uninitialized."""
    status = watchdog.watchdog_status(observer_dir=tmp_path)
    # No state file → no last_cycle → not stale
    assert status["is_stale"] is False
    assert status["last_cycle_at"] is None


# -- restart_observer (the recovery primitive) --------------------------


def test_restart_observer_calls_unregister_then_register(tmp_path, monkeypatch):
    """restart() = unregister + register w/ existing cadence."""
    calls = []

    def fake_unregister():
        calls.append("unregister")
        return True, "unregistered"

    def fake_register(cadence_minutes=60, daily_time="23:00", include_chat=True):
        calls.append(("register", cadence_minutes, daily_time, include_chat))
        return True, "registered"

    monkeypatch.setattr(watchdog, "_unregister_for_platform", fake_unregister)
    monkeypatch.setattr(watchdog, "_register_for_platform", fake_register)

    s = observer_state.ObserverState(
        armed=True, cadence_minutes=30, daily_retro_time="22:00",
    )
    observer_state.write_state(s, observer_dir=tmp_path)

    ok, msg = watchdog.restart_observer(observer_dir=tmp_path)
    assert ok is True
    assert calls[0] == "unregister"
    assert calls[1][0] == "register"
    assert calls[1][1] == 30  # cadence preserved
    assert calls[1][2] == "22:00"  # daily time preserved


def test_restart_observer_returns_failure_when_register_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "_unregister_for_platform",
                         lambda: (True, "unregistered"))
    monkeypatch.setattr(watchdog, "_register_for_platform",
                         lambda **k: (False, "register failed"))
    s = observer_state.ObserverState(armed=True, cadence_minutes=60)
    observer_state.write_state(s, observer_dir=tmp_path)

    ok, msg = watchdog.restart_observer(observer_dir=tmp_path)
    assert ok is False
    assert "fail" in msg.lower() or "register" in msg.lower()


def test_restart_observer_proceeds_even_if_unregister_fails(tmp_path, monkeypatch):
    """If unregister fails (e.g., task already gone), still try register."""
    monkeypatch.setattr(watchdog, "_unregister_for_platform",
                         lambda: (False, "task not found"))
    monkeypatch.setattr(watchdog, "_register_for_platform",
                         lambda **k: (True, "registered"))
    s = observer_state.ObserverState(armed=True, cadence_minutes=60)
    observer_state.write_state(s, observer_dir=tmp_path)

    ok, msg = watchdog.restart_observer(observer_dir=tmp_path)
    # Register-only success is acceptable as recovery
    assert ok is True


# -- platform dispatch --------------------------------------------------


def test_register_dispatches_to_cron_on_unix(monkeypatch):
    """On Linux/Mac, restart should use cron_scheduler."""
    from harness.observer import cron_scheduler

    monkeypatch.setattr(cron_scheduler.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(cron_scheduler, "register_cron_tasks",
                         lambda **k: (calls.append(("cron", k)) or (True, "ok")))
    monkeypatch.setattr("harness.observer.scheduler.register_tasks",
                         lambda **k: (calls.append(("win", k)) or (True, "ok")))

    ok, _ = watchdog._register_for_platform(cadence_minutes=60)
    assert ok is True
    # Only cron was called, not Windows scheduler
    assert any(c[0] == "cron" for c in calls)
    assert not any(c[0] == "win" for c in calls)


def test_register_dispatches_to_task_scheduler_on_windows(monkeypatch):
    from harness.observer import cron_scheduler

    monkeypatch.setattr(cron_scheduler.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(cron_scheduler, "register_cron_tasks",
                         lambda **k: (calls.append(("cron", k)) or (True, "ok")))
    monkeypatch.setattr("harness.observer.scheduler.register_tasks",
                         lambda **k: (calls.append(("win", k)) or (True, "ok")))

    ok, _ = watchdog._register_for_platform(cadence_minutes=60)
    assert ok is True
    # Only Windows scheduler was called
    assert any(c[0] == "win" for c in calls)
    assert not any(c[0] == "cron" for c in calls)


# -- the dashboard banner format ----------------------------------------


def test_dashboard_banner_returns_none_when_healthy(tmp_path):
    now = datetime.now(timezone.utc)
    s = observer_state.ObserverState(
        armed=True, cadence_minutes=60, last_cycle_at=now.isoformat(),
    )
    observer_state.write_state(s, observer_dir=tmp_path)
    banner = watchdog.dashboard_banner(observer_dir=tmp_path)
    assert banner is None


def test_dashboard_banner_returns_text_when_stale(tmp_path):
    """Operator-readable text per spec: 'observer task last fired Xh ago'."""
    now = datetime.now(timezone.utc)
    last = (now - timedelta(hours=5)).isoformat()
    s = observer_state.ObserverState(
        armed=True, cadence_minutes=60, last_cycle_at=last,
    )
    observer_state.write_state(s, observer_dir=tmp_path)
    banner = watchdog.dashboard_banner(observer_dir=tmp_path)
    assert banner is not None
    # Must say how long ago + offer next action
    assert "ago" in banner.lower() or "hour" in banner.lower()
    assert "restart" in banner.lower() or "observer" in banner.lower()


def test_dashboard_banner_includes_human_readable_duration(tmp_path):
    """Duration should be friendly: '5h ago' not '18000 seconds'."""
    now = datetime.now(timezone.utc)
    last = (now - timedelta(hours=5)).isoformat()
    s = observer_state.ObserverState(
        armed=True, cadence_minutes=60, last_cycle_at=last,
    )
    observer_state.write_state(s, observer_dir=tmp_path)
    banner = watchdog.dashboard_banner(observer_dir=tmp_path)
    assert banner is not None
    # 5h ago in some readable form
    assert "5" in banner


# -- humanize duration --------------------------------------------------


def test_humanize_seconds_minutes():
    assert "30" in watchdog._humanize_seconds(30 * 60)
    assert "min" in watchdog._humanize_seconds(30 * 60).lower()


def test_humanize_seconds_hours():
    assert "5" in watchdog._humanize_seconds(5 * 3600)
    assert "h" in watchdog._humanize_seconds(5 * 3600).lower()


def test_humanize_seconds_days():
    assert "2" in watchdog._humanize_seconds(2 * 86400)
    assert "d" in watchdog._humanize_seconds(2 * 86400).lower()
