"""Tests for harness.loops.supervisors — concrete + no-op + registry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.loops.state import LoopState
from harness.loops.supervisors import (
    BaseSupervisor,
    SupervisorResult,
    TestingSupervisor,
    run_supervisor,
)


# ---------------------------------------------------------------------------
# Base / registry
# ---------------------------------------------------------------------------


def test_run_supervisor_unknown_phase_returns_noop() -> None:
    state = LoopState()
    result = run_supervisor("unknown", state, project=Path("/fake"), now=datetime.now(timezone.utc))
    assert result.phase == "unknown"
    assert "pending Wave 6/B+" in result.log_summary


def test_run_supervisor_creativity_noop() -> None:
    state = LoopState()
    result = run_supervisor("creativity", state, project=Path("/fake"), now=datetime.now(timezone.utc))
    assert result.phase == "creativity"
    assert result.state_diff == {}
    assert result.escalation is None
    assert "pending Wave 6/B+" in result.log_summary


def test_run_supervisor_developing_noop() -> None:
    state = LoopState()
    result = run_supervisor("developing", state, project=Path("/fake"), now=datetime.now(timezone.utc))
    assert result.phase == "developing"
    assert "pending Wave 6/B+" in result.log_summary


def test_run_supervisor_integrating_noop() -> None:
    state = LoopState()
    result = run_supervisor("integrating", state, project=Path("/fake"), now=datetime.now(timezone.utc))
    assert result.phase == "integrating"
    assert "pending Wave 6/B+" in result.log_summary


def test_run_supervisor_process_improvement_noop() -> None:
    state = LoopState()
    result = run_supervisor(
        "process_improvement", state, project=Path("/fake"), now=datetime.now(timezone.utc)
    )
    assert result.phase == "process_improvement"
    assert "pending Wave 6/B+" in result.log_summary


# ---------------------------------------------------------------------------
# TestingSupervisor — pass
# ---------------------------------------------------------------------------


def test_testing_supervisor_pass(tmp_path: Path) -> None:
    state = LoopState()
    project = tmp_path
    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_dummy.py").write_text("def test_ok(): assert True\n", encoding="utf-8")

    ts = TestingSupervisor()
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    result = ts.run(state, project=project, now=now, tests_dir=tests_dir)

    assert result.phase == "testing"
    assert result.escalation is None
    assert result.state_diff["phase_cursors.testing.pytest_outcome"] == "pass"
    assert "passed" in result.state_diff["phase_cursors.testing.pytest_summary"]
    assert result.write_set == ["phase_cursors.testing"]


def test_testing_supervisor_uses_cadence_from_directives(tmp_path: Path) -> None:
    state = LoopState(
        operator_directives={"cadence_minutes": {"testing": 30}}
    )
    project = tmp_path
    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_dummy.py").write_text("def test_ok(): assert True\n", encoding="utf-8")

    ts = TestingSupervisor()
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    result = ts.run(state, project=project, now=now, tests_dir=tests_dir)

    next_due = result.state_diff["phase_cursors.testing.next_due_at"]
    assert "12:30:00" in next_due


# ---------------------------------------------------------------------------
# TestingSupervisor — fail / regressions
# ---------------------------------------------------------------------------


def test_testing_supervisor_fail_no_regression(tmp_path: Path) -> None:
    """When prior outcome is unknown, fail alone does NOT raise escalation."""
    state = LoopState()
    project = tmp_path
    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_broken.py").write_text("def test_nope(): assert False\n", encoding="utf-8")

    ts = TestingSupervisor()
    now = datetime.now(timezone.utc)
    result = ts.run(state, project=project, now=now, tests_dir=tests_dir)

    assert result.state_diff["phase_cursors.testing.pytest_outcome"] == "fail"
    assert result.escalation is None


def test_testing_supervisor_regression_from_pass(tmp_path: Path) -> None:
    """When prior outcome was pass, fail becomes L3 regression."""
    state = LoopState(
        phase_cursors={"testing": {"pytest_outcome": "pass"}}
    )
    project = tmp_path
    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_broken.py").write_text("def test_nope(): assert False\n", encoding="utf-8")

    ts = TestingSupervisor()
    now = datetime.now(timezone.utc)
    result = ts.run(state, project=project, now=now, tests_dir=tests_dir)

    assert result.escalation is not None
    assert result.escalation["level"] == "L3"
    assert "E_REGRESSION" in result.escalation["tag"]
    assert result.state_diff["phase_cursors.integrating.pending_merges"]


# ---------------------------------------------------------------------------
# TestingSupervisor — error / missing dir
# ---------------------------------------------------------------------------


def test_testing_supervisor_missing_tests_dir(tmp_path: Path) -> None:
    state = LoopState()
    ts = TestingSupervisor()
    now = datetime.now(timezone.utc)
    result = ts.run(state, project=tmp_path, now=now, tests_dir=tmp_path / "nope")

    assert result.escalation is not None
    assert result.escalation["level"] == "L4"
    assert "E_TEST_INFRA_BROKEN" in result.escalation["tag"]


def test_testing_supervisor_collection_error(tmp_path: Path) -> None:
    """Syntax errors in tests cause pytest exit != 0 and != 1 → L4."""
    state = LoopState()
    project = tmp_path
    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "bad.py").write_text("def test_x(}\n", encoding="utf-8")

    ts = TestingSupervisor()
    now = datetime.now(timezone.utc)
    result = ts.run(state, project=project, now=now, tests_dir=tests_dir)

    assert result.escalation is not None
    assert result.escalation["level"] == "L4"
    assert result.state_diff["phase_cursors.testing.pytest_outcome"] == "error"


# ---------------------------------------------------------------------------
# Write set
# ---------------------------------------------------------------------------


def test_testing_supervisor_write_set_nonempty(tmp_path: Path) -> None:
    state = LoopState()
    ts = TestingSupervisor()
    # Need a tests_dir that exists so we hit the post-pytest path (not the
    # early-return tests-dir-missing escalation).
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="1 passed in 0.01s\n", stderr=""
        )
        result = ts.run(
            state,
            project=tmp_path,
            now=datetime.now(timezone.utc),
            tests_dir=tests_dir,
        )
    assert result.write_set == ["phase_cursors.testing"]
