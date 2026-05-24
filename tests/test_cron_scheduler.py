"""W11-CROSS-PLATFORM-OBSERVER: tests for the cron-based observer scheduler.

Mocks the `crontab` binary via monkeypatching subprocess.run so the
tests don't touch the operator's real crontab.

Per W11 plan acceptance:
  - Generates valid cron syntax (`*/N * * * *` for N-divisor cadence)
  - Uses absolute path to harness CLI
  - register + unregister roundtrip preserves operator's non-harness entries
  - scheduler_status returns unified shape
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from harness.observer import cron_scheduler as cs


@pytest.fixture
def fake_crontab(monkeypatch):
    """Stub subprocess.run so cron operations don't touch real crontab.

    Returns a state dict tracking the simulated crontab content + the
    list of commands invoked.
    """
    state = {"content": "", "calls": []}

    def _fake_run(args, **kwargs):
        state["calls"].append(list(args))
        if args[:2] == ["crontab", "-l"]:
            if not state["content"]:
                return SimpleNamespace(
                    stdout="", stderr="no crontab for user\n", returncode=1,
                )
            return SimpleNamespace(
                stdout=state["content"], stderr="", returncode=0,
            )
        if args[:2] == ["crontab", "-"]:
            state["content"] = kwargs.get("input", "")
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(cs.subprocess, "run", _fake_run)
    monkeypatch.setattr(cs, "_has_crontab", lambda: True)
    return state


# -- crontab availability ------------------------------------------------


def test_has_crontab_returns_false_when_missing(monkeypatch):
    monkeypatch.setattr(cs.shutil, "which", lambda name: None)
    assert cs._has_crontab() is False


def test_has_crontab_returns_true_when_present(monkeypatch):
    monkeypatch.setattr(cs.shutil, "which",
                         lambda name: "/usr/bin/crontab" if name == "crontab" else None)
    assert cs._has_crontab() is True


def test_register_returns_error_when_crontab_missing(monkeypatch):
    monkeypatch.setattr(cs, "_has_crontab", lambda: False)
    ok, msg = cs.register_cron_tasks()
    assert ok is False
    assert "crontab" in msg.lower()


# -- register_cron_tasks --------------------------------------------------


def test_register_writes_cycle_and_retro_entries(fake_crontab):
    ok, msg = cs.register_cron_tasks(cadence_minutes=15, daily_time="08:30")
    assert ok is True
    content = fake_crontab["content"]
    # Two markers (cycle + retro) at minimum; +chat by default = three
    assert content.count(cs.MARKER_PREFIX) == 3
    # Cycle schedule
    assert "*/15 * * * *" in content
    # Retro schedule: 30 8 * * *
    assert "30 8 * * *" in content
    # Both task names present as markers
    assert cs.CYCLE_TASK_NAME in content
    assert cs.RETRO_TASK_NAME in content
    assert cs.CHAT_AUDIT_TASK_NAME in content


def test_register_uses_absolute_python_path(fake_crontab):
    """Cron entries should use absolute paths since cron strips $PATH."""
    cs.register_cron_tasks()
    content = fake_crontab["content"]
    # The command should have an absolute path (starts with / on *nix)
    # or 'python' bare (fallback).  Either way, NOT a relative './python'.
    assert "./python" not in content
    # And it should call `harness observer cycle-now`
    assert "harness observer cycle-now" in content


def test_register_uses_python_with_module_invocation(fake_crontab):
    cs.register_cron_tasks()
    content = fake_crontab["content"]
    assert "-m harness observer cycle-now" in content
    assert "-m harness observer daily-retro" in content


def test_register_falls_back_for_non_divisor_cadence(fake_crontab):
    """cadence_minutes=7 doesn't divide 60; falls back to hourly with note."""
    ok, msg = cs.register_cron_tasks(cadence_minutes=7)
    assert ok is True
    assert "warning" in msg.lower() or "hourly" in msg.lower()
    # Falls back to hourly
    assert "0 * * * *" in fake_crontab["content"]


def test_register_rejects_invalid_daily_time(fake_crontab):
    ok, msg = cs.register_cron_tasks(daily_time="25:99")
    assert ok is False
    assert "daily_time" in msg or "HH:MM" in msg


def test_register_excludes_chat_when_include_chat_false(fake_crontab):
    cs.register_cron_tasks(include_chat=False)
    content = fake_crontab["content"]
    # Two markers (cycle + retro), no chat
    assert content.count(cs.MARKER_PREFIX) == 2
    assert cs.CHAT_AUDIT_TASK_NAME not in content


# -- Idempotency: re-register replaces, doesn't duplicate ----------------


def test_register_is_idempotent_replaces_existing(fake_crontab):
    """Re-running register doesn't duplicate entries — old harness lines
    are removed + replaced atomically."""
    cs.register_cron_tasks(cadence_minutes=15)
    first_content = fake_crontab["content"]
    cs.register_cron_tasks(cadence_minutes=30)
    second_content = fake_crontab["content"]
    # Same number of marker lines (3) — no duplication
    assert second_content.count(cs.MARKER_PREFIX) == 3
    # Cadence updated
    assert "*/30 * * * *" in second_content
    assert "*/15 * * * *" not in second_content


def test_register_preserves_operator_non_harness_entries(fake_crontab):
    """Operator's existing cron entries (no marker) stay intact."""
    fake_crontab["content"] = (
        "# operator's daily backup\n"
        "0 2 * * * /home/op/backup.sh\n"
        "# unrelated thing\n"
        "*/5 * * * * /home/op/sync.sh\n"
    )
    cs.register_cron_tasks()
    content = fake_crontab["content"]
    # Operator entries preserved
    assert "/home/op/backup.sh" in content
    assert "/home/op/sync.sh" in content
    assert "# operator's daily backup" in content
    # Plus harness markers
    assert cs.CYCLE_TASK_NAME in content


# -- unregister_cron_tasks -----------------------------------------------


def test_unregister_removes_harness_entries_only(fake_crontab):
    fake_crontab["content"] = (
        "0 2 * * * /home/op/backup.sh\n"
        "# HARNESS_OBSERVER:XaxiuHarnessObserverCycle\n"
        "*/15 * * * * cd /path && python -m harness observer cycle-now\n"
        "*/5 * * * * /home/op/sync.sh\n"
    )
    ok, msg = cs.unregister_cron_tasks()
    assert ok is True
    content = fake_crontab["content"]
    # Operator entries preserved
    assert "/home/op/backup.sh" in content
    assert "/home/op/sync.sh" in content
    # Harness entries removed
    assert cs.MARKER_PREFIX not in content
    assert "harness observer cycle-now" not in content


def test_unregister_empty_crontab_is_noop(fake_crontab):
    """No crontab content → unregister succeeds with skip message."""
    fake_crontab["content"] = ""
    ok, msg = cs.unregister_cron_tasks()
    assert ok is True
    assert "nothing" in msg.lower() or "no" in msg.lower()


def test_unregister_returns_error_when_crontab_missing(monkeypatch):
    monkeypatch.setattr(cs, "_has_crontab", lambda: False)
    ok, msg = cs.unregister_cron_tasks()
    assert ok is False


# -- scheduler_status -----------------------------------------------------


def test_scheduler_status_reports_unarmed_initially(fake_crontab):
    """Fresh crontab with no harness entries → count_armed=0."""
    fake_crontab["content"] = "0 2 * * * /home/op/backup.sh\n"
    status = cs.scheduler_status()
    assert status["platform"] == "cron"
    assert status["count_armed"] == 0
    for task in status["tasks"].values():
        assert task["armed"] is False


def test_scheduler_status_reports_armed_after_register(fake_crontab):
    cs.register_cron_tasks(cadence_minutes=30)
    status = cs.scheduler_status()
    assert status["platform"] == "cron"
    assert status["count_armed"] == 3  # cycle + retro + chat
    assert status["tasks"][cs.CYCLE_TASK_NAME]["armed"] is True
    assert status["tasks"][cs.CYCLE_TASK_NAME]["schedule"] == "*/30 * * * *"


def test_scheduler_status_unavailable_when_crontab_missing(monkeypatch):
    monkeypatch.setattr(cs, "_has_crontab", lambda: False)
    status = cs.scheduler_status()
    assert status["platform"] == "unavailable"
    assert status["count_armed"] == 0
    assert "reason" in status


def test_scheduler_status_unified_shape_across_platforms(fake_crontab):
    """JSON shape MUST match the Windows scheduler_status to keep
    harness observer scheduler-status output uniform."""
    status = cs.scheduler_status()
    required_keys = {"platform", "tasks", "count_armed"}
    assert required_keys <= set(status.keys())
    # tasks is dict; each value has armed + schedule fields
    for task_name, info in status["tasks"].items():
        assert "armed" in info
        assert "schedule" in info


# -- Platform dispatch helper -------------------------------------------


def test_is_unix_like_returns_false_on_windows(monkeypatch):
    monkeypatch.setattr(cs.sys, "platform", "win32")
    assert cs.is_unix_like() is False


def test_is_unix_like_returns_true_on_linux(monkeypatch):
    monkeypatch.setattr(cs.sys, "platform", "linux")
    assert cs.is_unix_like() is True


def test_is_unix_like_returns_true_on_darwin(monkeypatch):
    monkeypatch.setattr(cs.sys, "platform", "darwin")
    assert cs.is_unix_like() is True


# -- Marker / filter unit tests -----------------------------------------


def test_filter_out_harness_entries_drops_markers_and_next_line():
    content = (
        "0 2 * * * /home/op/backup.sh\n"
        "# HARNESS_OBSERVER:XaxiuHarnessObserverCycle\n"
        "*/15 * * * * cd / && python -m harness observer cycle-now\n"
        "*/5 * * * * /home/op/sync.sh\n"
    )
    result = cs._filter_out_harness_entries(content)
    assert any("backup.sh" in line for line in result)
    assert any("sync.sh" in line for line in result)
    # Neither marker nor command survived
    assert not any(cs.MARKER_PREFIX in line for line in result)
    assert not any("harness observer cycle-now" in line for line in result)


def test_make_cron_entry_returns_marker_plus_line():
    entry = cs._make_cron_entry("MyTask", "*/15 * * * *", "/usr/bin/foo")
    assert len(entry) == 2
    assert entry[0] == f"{cs.MARKER_PREFIX}MyTask"
    assert entry[1] == "*/15 * * * * /usr/bin/foo"


# -- W11-CROSS-PLATFORM-OBSERVER audit fixes ----------------------------


def test_register_refuses_when_crontab_read_times_out(fake_crontab, monkeypatch):
    """K04: crontab -l timeout MUST NOT cause us to wipe operator entries."""
    def _raise_timeout(args, **kwargs):
        import subprocess as _sp
        if args[:2] == ["crontab", "-l"]:
            raise _sp.TimeoutExpired(cmd=args, timeout=5)
        # Track if we tried to write (we should NOT)
        fake_crontab["calls"].append(list(args))
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(cs.subprocess, "run", _raise_timeout)
    fake_crontab["content"] = "0 2 * * * /home/op/important.sh\n"
    ok, msg = cs.register_cron_tasks()
    assert ok is False
    assert "refus" in msg.lower() or "could not read" in msg.lower()
    # Critically: no write occurred → operator's crontab intact
    assert not any(c[:2] == ["crontab", "-"] for c in fake_crontab["calls"])


def test_unregister_refuses_when_crontab_read_fails(fake_crontab, monkeypatch):
    """K04 mirror: same protection for unregister."""
    def _raise_timeout(args, **kwargs):
        import subprocess as _sp
        if args[:2] == ["crontab", "-l"]:
            raise _sp.TimeoutExpired(cmd=args, timeout=5)
        fake_crontab["calls"].append(list(args))
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(cs.subprocess, "run", _raise_timeout)
    ok, msg = cs.unregister_cron_tasks()
    assert ok is False
    assert "refus" in msg.lower()


def test_register_shell_quotes_paths_with_metachars(fake_crontab, monkeypatch):
    """K09: a repo path containing shell metachars must be SAFELY quoted —
    i.e. shlex.quote wraps it in single quotes so the shell treats every
    character as literal.  Inside POSIX single quotes nothing is expanded,
    so `$(...)`, backticks, semicolons etc. are inert."""
    import shlex as _shlex
    from pathlib import Path
    evil = Path("/tmp/$(rm -rf$IFS/);echo")
    monkeypatch.setattr(cs, "_REPO_ROOT", evil)
    monkeypatch.setattr(cs, "_python_bin", lambda: "/usr/bin/python")
    cs.register_cron_tasks()
    content = fake_crontab["content"]
    # The single-quoted token must appear exactly as shlex would emit it
    expected_quoted = _shlex.quote(str(evil))
    assert expected_quoted in content
    # And the dangerous chars must ONLY appear inside that quoted token —
    # never raw.  Strip every occurrence of the quoted token and check.
    stripped = content.replace(expected_quoted, "")
    assert "$(" not in stripped
    assert ";echo" not in stripped


def test_scheduler_status_returns_populated_tasks_when_unavailable(monkeypatch):
    """K03: status['tasks'] must enumerate task names even when crontab
    is missing — agents iterating it should not KeyError."""
    monkeypatch.setattr(cs, "_has_crontab", lambda: False)
    status = cs.scheduler_status()
    assert status["platform"] == "unavailable"
    # Tasks dict populated with armed=False; agents can safely look up by name
    assert cs.CYCLE_TASK_NAME in status["tasks"]
    assert status["tasks"][cs.CYCLE_TASK_NAME]["armed"] is False
    assert status["count_armed"] == 0
