"""W10-PREFLIGHT-REMEDIATION-CARDS: fix-hint rendering tests.

Goal: every warn/fail check with a `fix` field prints a visually
distinct one-line "→ Run to fix: <command>" callout directly under
the check line.  Operators scanning a long preflight output should
immediately see the actionable command, not have to parse a buried
"fix:" hint.

Tests cover:
  - Fix hint rendered for warn checks
  - Fix hint rendered for fail checks
  - Fix hint NOT rendered for ok checks (nothing to fix)
  - Fix hint absent when check has no fix field
  - JSON format unaffected
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness import cli as _cli
from harness import preflight as _pf
from harness.preflight import PreflightCheck


def _stub_run_all(results):
    def _impl():
        return results
    return _impl


def test_warn_check_with_fix_renders_remediation_card(monkeypatch):
    """The W10 contract: warn-level fix hint shown as a distinct callout."""
    results = [
        PreflightCheck(
            name="observer", severity="warn",
            message="no observer tasks registered",
            duration_ms=10,
            fix="harness orchestrator install-observer-scheduler",
        ),
    ]
    monkeypatch.setattr(_pf, "run_all", _stub_run_all(results))
    monkeypatch.setattr(_cli, "run_all", _stub_run_all(results), raising=False)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["preflight"])
    assert "→ Run to fix:" in result.output
    assert "harness orchestrator install-observer-scheduler" in result.output


def test_fail_check_with_fix_renders_remediation_card(monkeypatch):
    results = [
        PreflightCheck(
            name="dpapi", severity="fail",
            message="DPAPI store unreadable",
            duration_ms=5,
            fix="harness env --rebuild",
        ),
    ]
    monkeypatch.setattr(_pf, "run_all", _stub_run_all(results))
    monkeypatch.setattr(_cli, "run_all", _stub_run_all(results), raising=False)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["preflight"])
    assert "→ Run to fix:" in result.output
    assert "harness env --rebuild" in result.output


def test_ok_check_with_fix_field_does_NOT_render_card(monkeypatch):
    """ok checks have nothing to fix; the card would just be noise."""
    results = [
        PreflightCheck(
            name="git_clean", severity="ok",
            message="working tree clean",
            duration_ms=3,
            fix="git stash",  # would be misleading on an ok check
        ),
    ]
    monkeypatch.setattr(_pf, "run_all", _stub_run_all(results))
    monkeypatch.setattr(_cli, "run_all", _stub_run_all(results), raising=False)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["preflight"])
    assert "→ Run to fix:" not in result.output


def test_check_without_fix_renders_no_card(monkeypatch):
    """No fix field -> no card."""
    results = [
        PreflightCheck(
            name="observer", severity="warn",
            message="no tasks registered",
            duration_ms=10,
            fix="",  # empty
        ),
    ]
    monkeypatch.setattr(_pf, "run_all", _stub_run_all(results))
    monkeypatch.setattr(_cli, "run_all", _stub_run_all(results), raising=False)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["preflight"])
    assert "→ Run to fix:" not in result.output


def test_multiple_warn_checks_render_independent_cards(monkeypatch):
    """Each warn with fix gets its own card."""
    results = [
        PreflightCheck(
            name="observer", severity="warn",
            message="no tasks", duration_ms=10,
            fix="harness orchestrator install-observer-scheduler",
        ),
        PreflightCheck(
            name="loops", severity="warn",
            message="not registered", duration_ms=8,
            fix="harness loop start",
        ),
    ]
    monkeypatch.setattr(_pf, "run_all", _stub_run_all(results))
    monkeypatch.setattr(_cli, "run_all", _stub_run_all(results), raising=False)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["preflight"])
    # Both fix commands appear in output, each under "Run to fix:"
    assert "harness orchestrator install-observer-scheduler" in result.output
    assert "harness loop start" in result.output
    assert result.output.count("→ Run to fix:") == 2


def test_json_format_does_not_render_card_text(monkeypatch):
    """JSON format keeps the existing PreflightCheck dump; no card text."""
    results = [
        PreflightCheck(
            name="observer", severity="warn",
            message="no tasks", duration_ms=10,
            fix="harness orchestrator install-observer-scheduler",
        ),
    ]
    monkeypatch.setattr(_pf, "run_all", _stub_run_all(results))
    monkeypatch.setattr(_cli, "run_all", _stub_run_all(results), raising=False)
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["preflight", "--format", "json"])
    assert "→ Run to fix:" not in result.output
    # But the fix field IS in the JSON output (CI consumers can parse it)
    assert "harness orchestrator install-observer-scheduler" in result.output
