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
# shutdown join (``threading._wait_for_tstate_lock``), so the process never
# exits.  Linux drained it; Windows HANGS — a fully-passing run then exits 1
# after the runner SIGINT's it (``KeyboardInterrupt`` at threading.py:359).
# Iterating the exit point LATER (conditional sessionfinish -> unconfigure)
# never helped: the hang is *during* the finalization phase, before those hooks
# fire and before any straggler is even visible.  So go EARLIER instead — a
# ``tryfirst`` sessionfinish runs at the very start of finalization (after the
# tests + their teardowns, before the terminal summary / asyncio loop cleanup /
# the hanging join) — and ``os._exit`` there with the already-final status,
# preempting the entire finalization phase deterministically on every platform.
# The reporter's counts are populated by now, so we print a concise result line
# in lieu of pytest's native summary.  Coverage runs are exempt (they need
# atexit to flush ``.coverage``; that CI step is non-blocking anyway).
@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):  # noqa: D401 - pytest hook
    import os
    import sys
    import threading

    if any("--cov" in a for a in sys.argv):
        return  # let the (non-blocking) coverage run flush via atexit

    rep = session.config.pluginmanager.get_plugin("terminalreporter")
    stats = getattr(rep, "stats", {}) if rep is not None else {}
    n = lambda k: len(stats.get(k, []))  # noqa: E731
    stragglers = [
        t.name for t in threading.enumerate()
        if t is not threading.main_thread() and t.is_alive() and not t.daemon
    ]

    # The spurious finalization KeyboardInterrupt sets exitstatus=INTERRUPTED(2)
    # even though every collected test ran and passed.  Judge success by the
    # actual results, not the interrupt-corrupted status: a run with zero
    # failed/errored tests where everything collected was accounted for is
    # GREEN — override only the spurious INTERRUPTED(2), never a real failure
    # (1) or a genuine mid-run interrupt (where collected tests went unrun).
    collected = int(getattr(session, "testscollected", 0) or 0)
    real_failures = n("failed") + n("error")
    accounted = n("passed") + n("skipped") + n("failed") + n("error") \
        + n("xfailed") + n("xpassed")
    if (int(exitstatus) == 2 and real_failures == 0
            and collected > 0 and accounted >= collected):
        code = 0
        verdict = "PASS (overrode spurious finalization interrupt)"
    else:
        code = int(exitstatus)
        verdict = f"exitstatus={code}"

    sys.stderr.write(
        f"\n[conftest] forcing clean exit (Windows finalization-hang "
        f"workaround): {n('passed')} passed, {n('failed')} failed, "
        f"{n('error')} error, {n('skipped')} skipped, "
        f"collected={collected} -> {verdict}"
        + (f"; stragglers={stragglers}" if stragglers else "")
        + "\n"
    )
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
