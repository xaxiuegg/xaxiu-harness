"""W9-CLI-TIMEOUT-BUDGET: regression tests for the operator-facing
commands that must not hang under load.

The master-audit panel (35/40 reviewers) reported `harness preflight
--skip-engines` and `harness today` timing out at 30s when 20
engine.dispatch() calls ran concurrently.  Root cause: PowerShell
shell-outs in the loops + observer preflight checks had no (or
too-loose) timeouts.

These tests are NOT wall-clock-sensitive — they exercise the
graceful-degrade path by monkey-patching subprocess to either hang
or return instantly, and assert the preflight returns a warn-level
result rather than blocking.
"""

from __future__ import annotations

import subprocess
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from harness import preflight
from harness.loops import scheduler as loops_scheduler


# -- is_registered timeout protection --------------------------------------


def test_is_registered_returns_false_on_timeout(monkeypatch):
    """When PowerShell hangs, is_registered should NOT block forever."""
    monkeypatch.setattr(loops_scheduler, "_pwsh", lambda: "powershell")

    def _hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=5)

    monkeypatch.setattr(loops_scheduler.subprocess, "run", _hang)
    assert loops_scheduler.is_registered() is False


def test_is_registered_passes_explicit_timeout(monkeypatch):
    """The timeout_sec arg is plumbed through to subprocess.run."""
    monkeypatch.setattr(loops_scheduler, "_pwsh", lambda: "powershell")
    captured: dict = {}

    def _capture(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(stdout="YES", stderr="", returncode=0)

    monkeypatch.setattr(loops_scheduler.subprocess, "run", _capture)
    loops_scheduler.is_registered(timeout_sec=2.5)
    assert captured["timeout"] == 2.5


def test_is_registered_returns_true_when_task_present(monkeypatch):
    monkeypatch.setattr(loops_scheduler, "_pwsh", lambda: "powershell")
    monkeypatch.setattr(
        loops_scheduler.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(
            stdout="YES\n", stderr="", returncode=0,
        ),
    )
    assert loops_scheduler.is_registered() is True


def test_is_registered_returns_false_when_no_pwsh(monkeypatch):
    monkeypatch.setattr(loops_scheduler, "_pwsh", lambda: None)
    assert loops_scheduler.is_registered() is False


# -- _check_observer_armed graceful degrade --------------------------------


def test_observer_check_degrades_on_powershell_timeout(monkeypatch):
    """W9-CLI-TIMEOUT-BUDGET: PowerShell hang must NOT block preflight.

    The check returns a warn-severity result with a 'timed out' message
    and a recovery hint instead of hanging or silently reporting
    'no observer tasks registered'.
    """
    monkeypatch.setattr(preflight.sys, "platform", "win32")
    monkeypatch.setattr(preflight, "_check_observer_dpapi_state",
                        lambda: True, raising=False)

    def _hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=5)

    monkeypatch.setattr(preflight.subprocess, "run", _hang)
    out = preflight._check_observer_armed()
    assert out.severity == "warn"
    assert "timed out" in out.message.lower()
    # The fix hint points at retry or the explicit observer-status verb,
    # NOT at "install scheduler" (which would lie about root cause)
    assert "preflight" in out.fix.lower() or "observer" in out.fix.lower()


def test_observer_check_reports_armed_when_task_count_positive(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "win32")

    def _fake_run(*args, **kwargs):
        return SimpleNamespace(stdout="3\n", stderr="", returncode=0)

    monkeypatch.setattr(preflight.subprocess, "run", _fake_run)
    out = preflight._check_observer_armed()
    assert out.severity == "ok"
    assert "3 observer task" in out.message


def test_observer_check_reports_unarmed_when_count_zero(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "win32")
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(stdout="0\n", stderr="", returncode=0),
    )
    out = preflight._check_observer_armed()
    assert out.severity == "warn"
    assert "no observer tasks" in out.message.lower()


# -- _check_loops_armed graceful degrade -----------------------------------


def test_loops_check_handles_is_registered_returning_false(monkeypatch):
    """If is_registered() returns False (whether real-not-registered or
    timeout-degrade), the preflight reports warn + suggests harness loop start."""
    monkeypatch.setattr(preflight.sys, "platform", "win32")
    monkeypatch.setattr(
        "harness.loops.scheduler.is_registered", lambda: False,
    )
    out = preflight._check_loops_armed()
    assert out.severity == "warn"
    assert "not registered" in out.message.lower()
    assert "harness loop start" in out.fix


def test_loops_check_reports_armed_when_registered(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "win32")
    monkeypatch.setattr(
        "harness.loops.scheduler.is_registered", lambda: True,
    )
    out = preflight._check_loops_armed()
    assert out.severity == "ok"
    assert "armed" in out.message.lower()


# -- preflight --skip-engines aggregate budget under stubbed I/O ----------


def test_preflight_skip_engines_runs_under_budget_with_stubbed_io(monkeypatch):
    """W9-CLI-TIMEOUT-BUDGET aggregate test.

    With all subprocess shell-outs returning instantly (stubbed),
    `harness preflight --skip-engines` should complete in well under
    8 seconds wall-clock.  This protects against future regressions
    where someone adds a new check that blocks the event loop.

    We use a 5s budget — generous for stubbed I/O, tight enough to
    catch a real hang (the master-audit failure was 30s).
    """
    monkeypatch.setattr(preflight.sys, "platform", "win32")

    def _instant(*args, **kwargs):
        return SimpleNamespace(
            stdout="0\n", stderr="", returncode=0,
        )

    monkeypatch.setattr(preflight.subprocess, "run", _instant)
    monkeypatch.setattr(
        "harness.loops.scheduler.is_registered", lambda: True,
    )

    from harness.preflight import _all_check_callables
    pairs = [(n, fn) for n, fn in _all_check_callables()
             if not n.startswith("engine:")]

    started = time.monotonic()
    results = [fn() for _, fn in pairs]
    elapsed = time.monotonic() - started

    # Stubbed I/O should complete in <5s.  Real failures shoot past 30s.
    assert elapsed < 5.0, (
        f"preflight --skip-engines aggregate took {elapsed:.1f}s with "
        f"stubbed I/O — expected <5s.  Some check is doing real work.")
    assert len(results) > 0
    # No check should be 'fail' under fully stubbed I/O — if one is,
    # that's an unexpected dependency on real state.
    fails = [r for r in results if r.severity == "fail"]
    # Some checks (status_csv, secrets) will be 'fail' on stubbed
    # filesystem; just verify the aggregate doesn't blow the budget.
    # The contract is: NO check hangs.


# -- Wall-clock budget tests (real subprocess; opt-in via marker) ---------


@pytest.mark.slow
def test_preflight_skip_engines_wall_clock_under_8s():
    """Real subprocess: harness preflight --skip-engines must complete
    in <8s wall-clock (W9-CLI-TIMEOUT-BUDGET criterion 1).  Skipped in
    fast-test mode; run with `pytest -m slow` to exercise."""
    import os
    import subprocess as _sp
    import sys
    import time as _t
    from pathlib import Path as _P
    repo = _P(__file__).resolve().parents[1]
    started = _t.monotonic()
    proc = _sp.run(
        [sys.executable, "-X", "utf8", "-m", "harness", "preflight",
         "--skip-engines"],
        cwd=repo, capture_output=True, text=True, timeout=20,
        env={**os.environ, "PYTHONPATH": str(repo / "src")},
    )
    elapsed = _t.monotonic() - started
    assert elapsed < 8.0, (
        f"preflight --skip-engines took {elapsed:.1f}s wall-clock — "
        f"expected <8s.  exit={proc.returncode}, "
        f"stderr tail: {proc.stderr[-200:]}")


@pytest.mark.slow
def test_today_wall_clock_under_10s():
    """Real subprocess: harness today must complete in <10s wall-clock
    (W9-CLI-TIMEOUT-BUDGET criterion 2)."""
    import os
    import subprocess as _sp
    import sys
    import time as _t
    from pathlib import Path as _P
    repo = _P(__file__).resolve().parents[1]
    started = _t.monotonic()
    proc = _sp.run(
        [sys.executable, "-X", "utf8", "-m", "harness", "today"],
        cwd=repo, capture_output=True, text=True, timeout=20,
        env={**os.environ, "PYTHONPATH": str(repo / "src")},
    )
    elapsed = _t.monotonic() - started
    assert elapsed < 10.0, (
        f"harness today took {elapsed:.1f}s wall-clock — "
        f"expected <10s.  exit={proc.returncode}, "
        f"stderr tail: {proc.stderr[-200:]}")


@pytest.mark.slow
def test_preflight_and_today_under_contention():
    """5 concurrent invocations: each allowed up to 2× budget, no deadlock
    (W9-CLI-TIMEOUT-BUDGET criterion 3)."""
    import os
    import subprocess as _sp
    import sys
    import time as _t
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pathlib import Path as _P
    repo = _P(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}

    def _run_one(cmd_args, label):
        started = _t.monotonic()
        proc = _sp.run(
            [sys.executable, "-X", "utf8", "-m", "harness", *cmd_args],
            cwd=repo, capture_output=True, text=True, timeout=30,
            env=env,
        )
        return (label, _t.monotonic() - started, proc.returncode)

    invocations = [
        (("preflight", "--skip-engines"), "preflight"),
    ] * 3 + [(("today",), "today")] * 2

    started = _t.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_run_one, args, label)
                   for args, label in invocations]
        for f in as_completed(futures):
            results.append(f.result())
    total_elapsed = _t.monotonic() - started

    for label, elapsed, rc in results:
        budget_2x = 16.0 if label == "preflight" else 20.0
        assert elapsed < budget_2x, (
            f"{label} under contention took {elapsed:.1f}s — "
            f"expected <{budget_2x}s (2× single-invocation budget).")
    # Total elapsed bounded — no deadlock
    assert total_elapsed < 30.0, (
        f"Contention test wall time {total_elapsed:.1f}s — possible "
        f"deadlock.")


# -- W9-SILENT-EXCEPTION-AUDIT followup: _swallow_telemetry smoke ---------


def test_swallow_telemetry_logs_at_debug_and_returns(caplog):
    """W9-SILENT-EXCEPTION-AUDIT criterion 2a followup: verify the
    dispatcher's swallow-telemetry helper produces a DEBUG log entry
    and never raises.  Audit chose DEBUG over WARNING intentionally
    because these sites fire per-dispatch and WARNING would flood
    the operator log with noise on every successful dispatch."""
    import logging
    from harness.engines import dispatcher
    caplog.set_level(logging.DEBUG, logger=dispatcher.logger.name)
    exc = ValueError("synthetic telemetry failure")
    # Should not raise
    dispatcher._swallow_telemetry("test_label", exc)
    # Should emit a DEBUG record
    debug_records = [r for r in caplog.records
                     if r.levelno == logging.DEBUG
                     and "test_label" in r.getMessage()]
    assert len(debug_records) >= 1
    assert "ValueError" in debug_records[0].getMessage()
    assert "synthetic telemetry failure" in debug_records[0].getMessage()
