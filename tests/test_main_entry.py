"""Smoke test for the `python -m harness` entry point.

WIRE-MAIN-ENTRY (2026-05-22): adds src/harness/__main__.py so the
coordinator's worker-spawn subprocess actually invokes the CLI.
Before this fix, ``python -m harness.cli`` loaded the module but
never called main() — workers exited 0 instantly with no checkpoint.

These tests guard the contract: ``python -m harness <verb>`` must
route through cli.main() and at minimum produce the same --help
output as the installed ``harness`` console script.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_python_m_harness_help_succeeds() -> None:
    """``python -m harness --help`` must print click help and exit 0."""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "harness", "--help"],
        env=_env(),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr[:500]}"
    # Click groups print "Usage: <prog> [OPTIONS] COMMAND [ARGS]..." and the
    # list of subcommands.  Both surfaces would be empty if __main__.py
    # were missing and the module loaded without invoking the group.
    assert "Usage:" in proc.stdout
    assert "Commands:" in proc.stdout


def test_python_m_harness_doctor_runs() -> None:
    """``python -m harness doctor`` must actually run the doctor (not exit 0 empty)."""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "harness", "doctor"],
        env=_env(),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # doctor exits 0 on ok/warn, 1 only on fail — we just need stdout to
    # show the preflight banner, proving the click group was invoked.
    assert "harness doctor" in proc.stdout or "harness doctor" in proc.stderr, (
        f"doctor produced no banner — __main__.py likely missing.  "
        f"rc={proc.returncode} stdout={proc.stdout[:300]} stderr={proc.stderr[:300]}"
    )


def test_python_m_harness_unknown_command_errors() -> None:
    """Sanity check: unknown subcommand exits non-zero (proves click is parsing)."""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "harness", "definitely-not-a-real-verb"],
        env=_env(),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0, (
        f"unknown subcommand should fail, got rc=0; stdout={proc.stdout[:300]}"
    )
