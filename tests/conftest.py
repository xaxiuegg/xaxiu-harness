"""Shared pytest configuration for the xaxiu-harness suite.

W14-RELIABILITY 2026-05-29 — platform-scoping Windows-only tests
=================================================================

xaxiu-harness is a *Windows-first* operator tool: several subsystems integrate
with OS facilities that only exist on Windows —

  * the observer scheduler registers **Windows Task Scheduler** tasks via
    PowerShell (``New-ScheduledTaskAction``); see ``harness/observer/scheduler.py``,
  * secret storage uses **DPAPI** (``ctypes.windll``), which raises
    ``NotImplementedError`` off-Windows by design.

The CI matrix runs on BOTH ``windows-latest`` and ``ubuntu-latest``.  The tests
listed below assert that those Windows-only code paths *proceed* (e.g. that the
install command reaches ``register_tasks``).  On Linux the command correctly
refuses before that point, so the assertions fail — a false red that says
nothing about whether the tool works.

This hook skips exactly those tests **only on non-Windows**.  Crucially they are
NOT disabled: on the ``windows-latest`` leg (``os.name == "nt"``) every one of
them still runs and must pass, so coverage of the Windows behaviour is fully
preserved.  This is the same platform-scoping ``@pytest.mark.skipif`` would
give, centralised here so the full set of OS-scoped tests is auditable in one
place.

If you add a test that genuinely exercises Windows Task Scheduler / DPAPI
*proceeding*, add it here (or mark it ``@pytest.mark.skipif(os.name != "nt")``).
"""
from __future__ import annotations

import os

import pytest

# file basename -> set of test function names that are Windows-only, or the
# string "*" meaning every test in that file.
_WINDOWS_ONLY: dict[str, object] = {
    # `observer install-scheduler --all` — entirely Task Scheduler registration.
    "test_observer_autoarm_all.py": "*",
    # CLI scheduler install/uninstall (the no-PowerShell guard tests).
    "test_observer.py": {
        "test_cli_observer_scheduler_install_no_ps",
        "test_cli_observer_scheduler_uninstall_no_ps",
    },
    # The two CLI-install variants (the other tests here mock register_tasks
    # directly and are platform-independent, so they keep running on Linux).
    "test_observer_chat_autoarm.py": {
        "test_cli_observer_install_scheduler_include_chat_flag",
        "test_cli_observer_install_scheduler_no_chat_by_default",
    },
    # W5-T orchestrator scheduler-install tests (schtasks/PowerShell).
    "test_w5_t_orchestrator.py": {
        "test_install_claude_scheduler_daily_for_long_intervals",
        "test_install_claude_scheduler_scaffolds_prompt_when_missing",
        "test_install_scheduler_daily_cadence",
        "test_install_scheduler_minute_cadence",
    },
    # Exercises `python -m harness.secrets.dpapi set` — DPAPI is Windows-only.
    "test_install_smoke.py": {
        "test_main_block_set_invokes_cli_set",
    },
}


def pytest_collection_modifyitems(config, items):  # noqa: D401 - pytest hook
    if os.name == "nt":
        return  # On Windows everything runs; nothing to scope out.
    skip = pytest.mark.skip(
        reason="Windows-only OS integration (Task Scheduler/PowerShell/DPAPI); "
               "exercised on the windows-latest CI leg."
    )
    for item in items:
        # Match on nodeid ("tests/<file>.py::<test>[param]") — stable across
        # pytest versions, unlike the deprecated item.fspath.
        head, _, tail = item.nodeid.partition("::")
        fname = head.replace("\\", "/").rsplit("/", 1)[-1]
        spec = _WINDOWS_ONLY.get(fname)
        if spec is None:
            continue
        test_name = tail.split("[", 1)[0]  # strip any parametrize suffix
        if spec == "*" or test_name in spec:
            item.add_marker(skip)


# W14-RELIABILITY 2026-05-29: some test leaves a thread that blocks Python's
# interpreter-shutdown join (``threading._wait_for_tstate_lock``), so the
# process never exits.  Linux drained it; Windows HANGS — a fully-passing run
# then exits 1 after the runner SIGINT's it (``KeyboardInterrupt`` at
# threading.py:359).  The CI-GREEN-4/5 attempts proved the offending thread is
# NOT visible at sessionfinish, so it blocks during atexit / interpreter
# shutdown (e.g. ``concurrent.futures._python_exit`` joining a stuck worker) —
# *after* the hooks.  So we stop trying to detect it and bypass the shutdown
# join: record the real exit status at sessionfinish, then ``os._exit`` from
# ``pytest_unconfigure`` (which runs AFTER the terminal summary, so the report
# still prints and the status is intact).  Coverage runs are exempt — they need
# atexit to flush ``.coverage`` and that CI step is non-blocking anyway.
_FORCED_EXIT_CODE: dict[str, object] = {"value": None}


def pytest_sessionfinish(session, exitstatus):  # noqa: D401 - pytest hook
    import sys

    if any("--cov" in a for a in sys.argv):
        return  # leave value None -> no force-exit; let coverage flush
    try:
        _FORCED_EXIT_CODE["value"] = int(exitstatus)
    except (TypeError, ValueError):
        _FORCED_EXIT_CODE["value"] = getattr(exitstatus, "value", 1)


def pytest_unconfigure(config):  # noqa: D401 - pytest hook
    code = _FORCED_EXIT_CODE["value"]
    if code is None:
        return  # collection error / coverage run -> normal exit path
    import os
    import sys
    import threading

    # Diagnostic only — name any straggler so a future change can root-fix it.
    main = threading.main_thread()
    lingering = [
        t for t in threading.enumerate()
        if t is not main and t.is_alive() and not t.daemon
    ]
    if lingering:
        sys.stderr.write(
            "\n[conftest] lingering non-daemon threads at exit: "
            + ", ".join(repr(t.name) for t in lingering) + "\n"
        )
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(code))
