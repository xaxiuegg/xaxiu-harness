"""W10-DAILY-QUICKSTART-VERB: regression tests for `harness daily`.

The 4-phase morning routine subprocess-composes existing verbs and
aggregates their exit codes into the same verdict label the operator
already learned from `harness preflight`.

Tests cover:
  - All-ok happy path (verdict PASS, exit 0)
  - One warn phase (verdict PASS-WITH-WARNINGS, exit 1)
  - One fail phase (verdict FAIL, exit 4)
  - Subprocess timeout downgrades to warn
  - --full flag drops --skip-engines from preflight invocation
  - --since-hours threads to morning-brief + today

Tests use Click's CliRunner + monkey-patch subprocess.run so we
don't actually shell out to the real verbs (which would be a 30s+
real run).
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness import cli as _cli


def _make_fake_run(per_phase_codes: dict[str, int],
                   call_log: list[list[str]] | None = None,
                   raise_timeout_for: str | None = None):
    """Return a fake subprocess.run that maps phase verb -> exit code.

    Phase keys: "preflight", "morning-brief", "today", "observer".
    """
    def _fake_run(args, **kwargs):
        if call_log is not None:
            call_log.append(list(args))
        # Identify which phase this is from args
        verb = None
        for token in args:
            if token in ("preflight", "morning-brief", "today", "observer"):
                verb = token
                break
        if raise_timeout_for is not None and verb == raise_timeout_for:
            raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 30))
        rc = per_phase_codes.get(verb, 0)
        return SimpleNamespace(
            stdout=f"[{verb}] fake-output ok",
            stderr="",
            returncode=rc,
        )
    return _fake_run


# -- Happy path: all ok ---------------------------------------------------


def test_daily_all_ok_returns_pass(monkeypatch):
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 0, "morning-brief": 0,
                        "today": 0, "observer": 0}),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["daily"])
    assert result.exit_code == 0
    assert "Aggregate verdict: PASS" in result.output
    assert "ready" in result.output.lower()
    # All four phases ran (look for the headers)
    assert "1/4 preflight" in result.output
    assert "2/4 morning-brief" in result.output
    assert "3/4 today" in result.output
    assert "4/4 observer flags" in result.output


def test_daily_default_uses_skip_engines(monkeypatch):
    """Default mode skips engines for snappier morning routine."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 0, "morning-brief": 0,
                        "today": 0, "observer": 0}, call_log=calls),
    )
    runner = CliRunner()
    runner.invoke(_cli.cli, ["daily"])
    # Find the preflight call
    preflight_calls = [c for c in calls if "preflight" in c]
    assert preflight_calls
    assert "--skip-engines" in preflight_calls[0]


def test_daily_full_includes_engines(monkeypatch):
    """--full drops --skip-engines so live engine probes run."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 0, "morning-brief": 0,
                        "today": 0, "observer": 0}, call_log=calls),
    )
    runner = CliRunner()
    runner.invoke(_cli.cli, ["daily", "--full"])
    preflight_calls = [c for c in calls if "preflight" in c]
    assert preflight_calls
    assert "--skip-engines" not in preflight_calls[0]


def test_daily_passes_since_hours_to_brief_and_today(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 0, "morning-brief": 0,
                        "today": 0, "observer": 0}, call_log=calls),
    )
    runner = CliRunner()
    runner.invoke(_cli.cli, ["daily", "--since-hours", "48"])
    # Both morning-brief and today should see --since-hours 48
    for verb in ("morning-brief", "today"):
        verb_calls = [c for c in calls if verb in c]
        assert verb_calls, f"no call for {verb}"
        assert "--since-hours" in verb_calls[0]
        assert "48" in verb_calls[0]


# -- Mixed-severity phases aggregate to worst -----------------------------


def test_daily_one_warn_phase_returns_pass_with_warnings(monkeypatch):
    """preflight warned (exit 1) but others ok -> aggregate PASS-WITH-WARNINGS."""
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 1, "morning-brief": 0,
                        "today": 0, "observer": 0}),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["daily"])
    assert result.exit_code == 1
    assert "Aggregate verdict: PASS-WITH-WARNINGS" in result.output
    # Operator sees the per-phase breakdown when verdict != PASS
    assert "1/4=1" in result.output


def test_daily_one_fail_phase_returns_fail(monkeypatch):
    """preflight failed (exit 4) -> aggregate FAIL even if others ok."""
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 4, "morning-brief": 0,
                        "today": 0, "observer": 1}),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["daily"])
    assert result.exit_code == 4
    assert "Aggregate verdict: FAIL" in result.output
    assert "blocker" in result.output.lower() or "refuses" in result.output.lower()


def test_daily_fail_dominates_warn(monkeypatch):
    """Both fail and warn present -> fail wins."""
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 1, "morning-brief": 4,
                        "today": 0, "observer": 0}),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["daily"])
    assert result.exit_code == 4
    assert "Aggregate verdict: FAIL" in result.output


# -- Timeout degrades to warn --------------------------------------------


def test_daily_timeout_phase_degrades_to_warn(monkeypatch):
    """A timed-out phase should NOT crash the daily run — degrade to warn."""
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 0, "morning-brief": 0,
                        "today": 0, "observer": 0},
                       raise_timeout_for="preflight"),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["daily"])
    # Timeout treated as warn (exit 1)
    assert result.exit_code == 1
    assert "TIMEOUT" in result.output


# -- Phase ordering preserved --------------------------------------------


def test_daily_runs_phases_in_documented_order(monkeypatch):
    """Phase ordering matters for the operator: preflight first (gates
    autonomous mode), then context (brief + today), then escalations."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        _cli.subprocess, "run",
        _make_fake_run({"preflight": 0, "morning-brief": 0,
                        "today": 0, "observer": 0}, call_log=calls),
    )
    runner = CliRunner()
    runner.invoke(_cli.cli, ["daily"])
    # Extract just the phase verb from each call
    verbs_in_order = []
    for c in calls:
        for token in c:
            if token in ("preflight", "morning-brief", "today", "observer"):
                verbs_in_order.append(token)
                break
    assert verbs_in_order == ["preflight", "morning-brief",
                              "today", "observer"]
