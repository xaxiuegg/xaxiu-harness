"""W10-PREFLIGHT-EXIT-CODE-SEMANTICS: verdict-label translation tests.

The non-technical operator historically reads "exit 1" as FAIL when
the harness intends "warning, still ok to proceed".  The new
verdict_label helper translates exit codes into plain-language
(short_verdict, explanation) pairs that the CLI prints after the
per-check listing.

Tests cover:
  - Pure translation of each known exit code
  - Unknown exit codes don't crash
  - CLI integration prints the verdict line
  - overall_exit_code semantics unchanged (regression-protect CI
    scripts that depend on the integer values)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.preflight import (
    PreflightCheck,
    overall_exit_code,
    verdict_label,
)


# -- verdict_label translation --------------------------------------------


def test_verdict_label_zero_is_pass():
    label, explanation = verdict_label(0)
    assert label == "PASS"
    assert "ready" in explanation.lower()


def test_verdict_label_one_is_pass_with_warnings():
    label, explanation = verdict_label(1)
    assert label == "PASS-WITH-WARNINGS"
    # Critical for the operator: they need to KNOW exit 1 is still ok
    assert "proceed" in explanation.lower() or "actionable" in explanation.lower()


def test_verdict_label_four_is_fail():
    label, explanation = verdict_label(4)
    assert label == "FAIL"
    assert "blocker" in explanation.lower() or "refuses" in explanation.lower()


def test_verdict_label_unknown_is_marked_unknown():
    """Defensive: exit code 7 (say, future) should not crash."""
    label, explanation = verdict_label(7)
    assert label == "UNKNOWN"
    assert "7" in explanation


def test_verdict_label_negative_is_marked_unknown():
    label, explanation = verdict_label(-1)
    assert label == "UNKNOWN"


# -- overall_exit_code semantics preserved --------------------------------


def _mk(severity: str) -> PreflightCheck:
    return PreflightCheck(name="x", severity=severity, message="m")


def test_overall_exit_code_all_ok_is_zero():
    assert overall_exit_code([_mk("ok"), _mk("ok")]) == 0


def test_overall_exit_code_warn_is_one():
    assert overall_exit_code([_mk("ok"), _mk("warn")]) == 1


def test_overall_exit_code_fail_is_four():
    """Fail dominates warn."""
    assert overall_exit_code([_mk("warn"), _mk("fail")]) == 4


def test_overall_exit_code_empty_is_zero():
    """No checks = all ok."""
    assert overall_exit_code([]) == 0


# -- CLI integration: verdict line printed --------------------------------


def test_cli_preflight_prints_verdict_line_on_ok(monkeypatch):
    """When all checks ok, CLI prints the PASS verdict + explanation."""
    from harness import cli
    from harness import preflight as _pf

    # Stub run_all to return all-ok
    def _stub_run_all():
        return [PreflightCheck(name="git_clean", severity="ok",
                               message="clean", duration_ms=10)]

    monkeypatch.setattr(_pf, "run_all", _stub_run_all)
    monkeypatch.setattr(cli, "run_all", _stub_run_all, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli.cli, ["preflight"])
    # exit 0 (still ok semantics)
    assert result.exit_code == 0
    assert "Verdict: PASS" in result.output
    assert "ready" in result.output.lower()


def test_cli_preflight_prints_verdict_line_on_warn(monkeypatch):
    """When at least one warn check, CLI prints PASS-WITH-WARNINGS verdict.

    Critical: the operator sees that exit 1 is NOT a fail."""
    from harness import cli
    from harness import preflight as _pf

    def _stub_run_all():
        return [
            PreflightCheck(name="git_clean", severity="ok",
                           message="clean", duration_ms=10),
            PreflightCheck(name="observer", severity="warn",
                           message="no tasks registered",
                           duration_ms=10),
        ]

    monkeypatch.setattr(_pf, "run_all", _stub_run_all)
    monkeypatch.setattr(cli, "run_all", _stub_run_all, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli.cli, ["preflight"])
    assert result.exit_code == 1
    assert "Verdict: PASS-WITH-WARNINGS" in result.output
    # The operator's mental-model reassurance
    assert "proceed" in result.output.lower() or "actionable" in result.output.lower()


def test_cli_preflight_prints_verdict_line_on_fail(monkeypatch):
    from harness import cli
    from harness import preflight as _pf

    def _stub_run_all():
        return [
            PreflightCheck(name="dpapi", severity="fail",
                           message="unreadable", duration_ms=10),
        ]

    monkeypatch.setattr(_pf, "run_all", _stub_run_all)
    monkeypatch.setattr(cli, "run_all", _stub_run_all, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli.cli, ["preflight"])
    assert result.exit_code == 4
    assert "Verdict: FAIL" in result.output
    assert "blocker" in result.output.lower() or "refuses" in result.output.lower()


def test_cli_preflight_json_format_does_not_print_verdict_line(monkeypatch):
    """JSON format is for CI consumption — keep it clean, no extra line.
    The verdict is implicit in the existing exit code."""
    from harness import cli
    from harness import preflight as _pf

    def _stub_run_all():
        return [PreflightCheck(name="x", severity="ok",
                               message="m", duration_ms=10)]

    monkeypatch.setattr(_pf, "run_all", _stub_run_all)
    monkeypatch.setattr(cli, "run_all", _stub_run_all, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli.cli, ["preflight", "--format", "json"])
    assert result.exit_code == 0
    # JSON output should not contain the "Verdict:" prose
    assert "Verdict:" not in result.output
