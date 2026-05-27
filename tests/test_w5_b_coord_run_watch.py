"""W5-B: `coord run --watch` auto-tick loop for unattended overnight runs.

Drives the coord state machine end-to-end without an operator needing
to invoke `--resume` for every transition.  Includes integrator
auto-fire when the run reaches INTEGRATING so a single command
survives PLANNING -> RUNNING -> workers -> INTEGRATING -> DONE.

Plus W5-G: budget warns 'Unknown engine' only on truly unknown engines,
silencing the noise from the documented `mock` pseudo-engine.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.budget import _compute_cost


# ---------------------------------------------------------------------------
# W5-G: mock-engine doesn't trigger the Unknown engine warning
# ---------------------------------------------------------------------------

def test_compute_cost_mock_engine_silent(caplog: pytest.LogCaptureFixture) -> None:
    """`mock` is documented free; should NOT log Unknown engine warning.

    P3 audit fix (2026-05-27): ``_compute_cost`` now returns
    ``(cost, cost_known)``.  Documented free engines stay silent AND
    report cost_known=True (i.e. the $0 is known, not guessed).
    """
    with caplog.at_level(logging.WARNING):
        cost, cost_known = _compute_cost("mock", input_tokens=100, output_tokens=50)
    assert cost == 0.0
    assert cost_known is True
    assert "Unknown engine" not in caplog.text


def test_compute_cost_truly_unknown_engine_warns(caplog: pytest.LogCaptureFixture) -> None:
    """Genuinely unknown engine should still log the warning AND
    report ``cost_known=False`` so the ledger row is flagged
    (P3 audit fix 2026-05-27)."""
    with caplog.at_level(logging.WARNING):
        cost, cost_known = _compute_cost(
            "totally-fake-engine-xyz", input_tokens=100, output_tokens=50,
        )
    assert cost == 0.0
    assert cost_known is False
    assert "Unknown engine" in caplog.text
    assert "totally-fake-engine-xyz" in caplog.text


def test_compute_cost_mock_variants_all_silent(caplog: pytest.LogCaptureFixture) -> None:
    """All documented mock spellings stay silent and report cost_known=True."""
    with caplog.at_level(logging.WARNING):
        for name in ["mock", "mock-engine", "mockengine"]:
            cost, cost_known = _compute_cost(name, input_tokens=10, output_tokens=10)
            assert cost == 0.0
            assert cost_known is True
    assert "Unknown engine" not in caplog.text


# ---------------------------------------------------------------------------
# W5-B: --watch flag is exposed and documented
# ---------------------------------------------------------------------------

def test_coord_run_watch_flag_in_help() -> None:
    """The --watch family of flags should appear in `coord run --help`."""
    runner = CliRunner()
    result = runner.invoke(cli, ["coord", "run", "--help"])
    assert result.exit_code == 0
    assert "--watch" in result.output
    assert "--watch-interval" in result.output
    assert "--watch-max-seconds" in result.output
    assert "unattended overnight" in result.output


def test_coord_run_watch_max_seconds_default() -> None:
    """Default --watch-max-seconds should be 1h (3600s) for overnight runs."""
    runner = CliRunner()
    result = runner.invoke(cli, ["coord", "run", "--help"])
    assert "default 1h" in result.output or "default 3600" in result.output


# Note: actual end-to-end --watch behavior is exercised by the manual
# W4-L proof in coord/coverage/W4_L_E2E_PROOF.md and the smoke test in
# tests/test_coord_smoke_e2e.py.  Running the live loop here would spawn
# real subprocesses and create a worktree, which is out-of-scope for unit
# tests.
