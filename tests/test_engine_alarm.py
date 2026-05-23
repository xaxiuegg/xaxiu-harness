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
