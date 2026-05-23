"""Tests for harness.engine_alarm — W6-C2 dead-engine alarm."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import engine_alarm
from harness.engine_alarm import (
    consecutive_failures,
    check_engine_alarm,
    dead_engines,
)


def _write_log(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# consecutive_failures
# ---------------------------------------------------------------------------


def test_consecutive_failures_empty_log_returns_zero(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    log.write_text("", encoding="utf-8")
    assert consecutive_failures("deepseek", log_path=log) == 0


def test_consecutive_failures_missing_log_returns_zero(tmp_path: Path) -> None:
    log = tmp_path / "absent.jsonl"
    assert consecutive_failures("deepseek", log_path=log) == 0


def test_consecutive_failures_counts_tail_failures(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    _write_log(log, [
        {"backend": "deepseek", "outcome": "success"},
        {"backend": "deepseek", "outcome": "failure"},
        {"backend": "deepseek", "outcome": "failure"},
        {"backend": "deepseek", "outcome": "failure"},
    ])
    assert consecutive_failures("deepseek", log_path=log) == 3


def test_consecutive_failures_stops_at_success(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    _write_log(log, [
        {"backend": "deepseek", "outcome": "failure"},
        {"backend": "deepseek", "outcome": "failure"},
        {"backend": "deepseek", "outcome": "success"},
        {"backend": "deepseek", "outcome": "failure"},
        {"backend": "deepseek", "outcome": "failure"},
    ])
    # Walking from tail: 2 failures, then success breaks the streak.
    assert consecutive_failures("deepseek", log_path=log) == 2


def test_consecutive_failures_ignores_other_engines(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    _write_log(log, [
        {"backend": "deepseek", "outcome": "failure"},
        {"backend": "kimi", "outcome": "success"},  # noise
        {"backend": "deepseek", "outcome": "failure"},
        {"backend": "mimo", "outcome": "success"},  # noise
        {"backend": "deepseek", "outcome": "failure"},
    ])
    # 3 deepseek failures, kimi/mimo noise filtered out.
    assert consecutive_failures("deepseek", log_path=log) == 3


def test_consecutive_failures_zero_when_all_success(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    _write_log(log, [
        {"backend": "deepseek", "outcome": "success"},
        {"backend": "deepseek", "outcome": "success"},
    ])
    assert consecutive_failures("deepseek", log_path=log) == 0


# ---------------------------------------------------------------------------
# check_engine_alarm — state transition
# ---------------------------------------------------------------------------


def test_check_engine_alarm_below_threshold_no_transition(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    alarm = tmp_path / "alarms.json"
    _write_log(log, [
        {"backend": "deepseek", "outcome": "failure"},
        {"backend": "deepseek", "outcome": "failure"},
    ])
    is_dead, streak, transition = check_engine_alarm(
        "deepseek", threshold=5, log_path=log, alarm_path=alarm,
    )
    assert is_dead is False
    assert streak == 2
    assert transition is False
    assert not alarm.exists()  # no state file written


def test_check_engine_alarm_at_threshold_fires_transition(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    alarm = tmp_path / "alarms.json"
    _write_log(log, [{"backend": "kimi", "outcome": "failure"}] * 5)
    is_dead, streak, transition = check_engine_alarm(
        "kimi", threshold=5, log_path=log, alarm_path=alarm,
    )
    assert is_dead is True
    assert streak == 5
    assert transition is True
    # Alarm state file is written
    state = json.loads(alarm.read_text(encoding="utf-8"))
    assert state["kimi"]["dead"] is True
    assert state["kimi"]["streak_at_alarm"] == 5
    assert "fired_at" in state["kimi"]


def test_check_engine_alarm_already_dead_no_double_fire(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    alarm = tmp_path / "alarms.json"
    _write_log(log, [{"backend": "kimi", "outcome": "failure"}] * 7)
    # First call fires
    _, _, transition_1 = check_engine_alarm(
        "kimi", threshold=5, log_path=log, alarm_path=alarm,
    )
    assert transition_1 is True
    # Second call: same dead state, no new transition
    is_dead, streak, transition_2 = check_engine_alarm(
        "kimi", threshold=5, log_path=log, alarm_path=alarm,
    )
    assert is_dead is True
    assert streak == 7
    assert transition_2 is False


def test_check_engine_alarm_recovery_clears_state(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    alarm = tmp_path / "alarms.json"
    # 5 failures → dead
    _write_log(log, [{"backend": "mimo", "outcome": "failure"}] * 5)
    check_engine_alarm("mimo", threshold=5, log_path=log, alarm_path=alarm)
    # Add a success at the tail → no longer dead
    _write_log(log, [
        *[{"backend": "mimo", "outcome": "failure"}] * 5,
        {"backend": "mimo", "outcome": "success"},
    ])
    is_dead, streak, transition = check_engine_alarm(
        "mimo", threshold=5, log_path=log, alarm_path=alarm,
    )
    assert is_dead is False
    assert streak == 0
    assert transition is False
    state = json.loads(alarm.read_text(encoding="utf-8"))
    assert state["mimo"]["dead"] is False
    assert "recovered_at" in state["mimo"]


def test_check_engine_alarm_redeath_after_recovery_fires_again(tmp_path: Path) -> None:
    """An engine that recovered and then dies again should fire a fresh
    transition (operator may want notification on each death event)."""
    log = tmp_path / "perf.jsonl"
    alarm = tmp_path / "alarms.json"
    # Initial death
    _write_log(log, [{"backend": "kimi", "outcome": "failure"}] * 5)
    check_engine_alarm("kimi", threshold=5, log_path=log, alarm_path=alarm)
    # Recovery (success at tail clears the streak)
    _write_log(log, [
        *[{"backend": "kimi", "outcome": "failure"}] * 5,
        {"backend": "kimi", "outcome": "success"},
    ])
    check_engine_alarm("kimi", threshold=5, log_path=log, alarm_path=alarm)
    # Re-death — 5 fresh failures after the recovery
    _write_log(log, [
        *[{"backend": "kimi", "outcome": "failure"}] * 5,
        {"backend": "kimi", "outcome": "success"},
        *[{"backend": "kimi", "outcome": "failure"}] * 5,
    ])
    _, _, transition = check_engine_alarm(
        "kimi", threshold=5, log_path=log, alarm_path=alarm,
    )
    assert transition is True, "re-death after recovery should re-fire"


# ---------------------------------------------------------------------------
# dead_engines — preflight summary
# ---------------------------------------------------------------------------


def test_dead_engines_returns_only_above_threshold(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    _write_log(log, [
        *[{"backend": "kimi", "outcome": "failure"}] * 7,    # dead
        *[{"backend": "mimo", "outcome": "failure"}] * 3,    # alive (below)
        *[{"backend": "deepseek", "outcome": "success"}] * 1,  # healthy
    ])
    result = dead_engines(
        engines=["kimi", "mimo", "deepseek"],
        threshold=5,
        log_path=log,
    )
    assert result == {"kimi": 7}


def test_dead_engines_empty_when_all_healthy(tmp_path: Path) -> None:
    log = tmp_path / "perf.jsonl"
    _write_log(log, [
        {"backend": "kimi", "outcome": "success"},
        {"backend": "mimo", "outcome": "success"},
    ])
    assert dead_engines(
        engines=["kimi", "mimo"], threshold=5, log_path=log,
    ) == {}


def test_dead_engines_default_engine_list(tmp_path: Path) -> None:
    """When engines=None, the function probes the default 5-engine list."""
    log = tmp_path / "perf.jsonl"
    _write_log(log, [{"backend": "anthropic", "outcome": "failure"}] * 5)
    result = dead_engines(threshold=5, log_path=log)
    assert "anthropic" in result
    assert result["anthropic"] == 5


# ---------------------------------------------------------------------------
# fire_dead_engine_alarm — stderr + toast (toast mocked)
# ---------------------------------------------------------------------------


def test_fire_dead_engine_alarm_prints_L4_to_stderr(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mock the toast so we don't actually fire one in tests
    monkeypatch.setattr("harness.errors.fire_windows_toast",
                        lambda *a, **kw: True)
    engine_alarm.fire_dead_engine_alarm("kimi", streak=7)
    captured = capsys.readouterr()
    assert "L4.engines.E_DEAD_ENGINE" in captured.err
    assert "kimi" in captured.err
    assert "7 consecutive" in captured.err


def test_end_to_end_alarm_pipeline_5_failures_fires_toast(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end smoke: 5 consecutive kimi failures in a fresh perf log
    cause check_engine_alarm to return transition=True AND
    fire_dead_engine_alarm to emit the L4 stderr + invoke
    fire_windows_toast.  This exercises the full
    log → streak → alarm → toast pathway in one test (the W6-C2
    audit's E2E evidence requirement)."""
    log = tmp_path / "perf.jsonl"
    alarm = tmp_path / "alarms.json"
    _write_log(log, [{"backend": "kimi", "outcome": "failure"}] * 5)

    toast_calls: list[dict] = []
    monkeypatch.setattr(
        "harness.errors.fire_windows_toast",
        lambda title, body: toast_calls.append({"title": title, "body": body})
        or True,
    )

    # Step 1: streak check
    is_dead, streak, transition = check_engine_alarm(
        "kimi", threshold=5, log_path=log, alarm_path=alarm,
    )
    assert is_dead is True
    assert streak == 5
    assert transition is True

    # Step 2: fire alarm (simulates what dispatcher.py does on transition)
    engine_alarm.fire_dead_engine_alarm("kimi", streak)

    # Step 3: verify L4 stderr + toast were both invoked
    captured = capsys.readouterr()
    assert "L4.engines.E_DEAD_ENGINE" in captured.err
    assert "kimi" in captured.err
    assert "5 consecutive" in captured.err
    assert len(toast_calls) == 1
    assert "kimi" in toast_calls[0]["title"]
    assert "engine dead" in toast_calls[0]["title"]
    assert "5 consecutive failures" in toast_calls[0]["body"]

    # Step 4: subsequent check (without log mutation) does NOT re-fire
    # — alarm state file debounces.  This is the no-spam guarantee.
    is_dead_2, streak_2, transition_2 = check_engine_alarm(
        "kimi", threshold=5, log_path=log, alarm_path=alarm,
    )
    assert is_dead_2 is True
    assert streak_2 == 5
    assert transition_2 is False, "duplicate-fire debounce broken"


def test_dispatcher_integration_hook_visible() -> None:
    """W6-C2 dispatcher integration: confirm the alarm hook exists at
    the documented call site so future refactors that move the
    fallback log entry don't silently drop the alarm.  Source-level
    sentinel; complements the unit tests by guarding the call-site
    contract."""
    from pathlib import Path
    dispatcher_src = (
        Path(__file__).resolve().parents[1]
        / "src" / "harness" / "engines" / "dispatcher.py"
    ).read_text(encoding="utf-8")
    assert "check_engine_alarm" in dispatcher_src, (
        "dispatcher.py no longer references check_engine_alarm — "
        "W6-C2 hook was removed or moved without test update"
    )
    assert "fire_dead_engine_alarm" in dispatcher_src
    # The hook must be inside the fallback log path so each per-engine
    # failure triggers the streak check (not just at end of dispatch).
    fallback_idx = dispatcher_src.find('outcome="fallback"')
    hook_idx = dispatcher_src.find("check_engine_alarm")
    assert fallback_idx > 0 and hook_idx > fallback_idx, (
        "alarm hook should be AFTER the fallback log entry so each "
        "per-engine failure is counted"
    )
