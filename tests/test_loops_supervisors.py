"""Tests for harness.loops.supervisors — concrete + no-op + registry."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.loops.state import ActiveDispatch, LoopState, WaveEntry
from harness.engines.dispatcher import DispatchResult
from harness.loops.supervisors import (
    BaseSupervisor,
    DevelopingSupervisor,
    IntegratingSupervisor,
    SupervisorResult,
    TestingSupervisor,
    CreativitySupervisor,
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


def test_run_supervisor_creativity_real() -> None:
    """Wave 6/C: real CreativitySupervisor returns phase + result, no NoOp marker."""
    state = LoopState()
    result = run_supervisor("creativity", state, project=Path("/fake"), now=datetime.now(timezone.utc))
    assert result.phase == "creativity"
    assert "pending Wave 6/B+" not in result.log_summary


def test_run_supervisor_developing_real() -> None:
    state = LoopState()
    result = run_supervisor("developing", state, project=Path("/fake"), now=datetime.now(timezone.utc))
    assert result.phase == "developing"
    assert "pending Wave 6/B+" not in result.log_summary


def test_run_supervisor_integrating_real() -> None:
    state = LoopState()
    result = run_supervisor("integrating", state, project=Path("/fake"), now=datetime.now(timezone.utc))
    assert result.phase == "integrating"
    assert "pending Wave 6/B+" not in result.log_summary


def test_run_supervisor_process_improvement_real() -> None:
    state = LoopState()
    result = run_supervisor(
        "process_improvement", state, project=Path("/fake"), now=datetime.now(timezone.utc)
    )
    assert result.phase == "process_improvement"
    assert "pending Wave 6/B+" not in result.log_summary


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


# ---------------------------------------------------------------------------
# DevelopingSupervisor
# ---------------------------------------------------------------------------


class TestDevelopingSupervisor:
    def test_empty_wave_plan_returns_noop(self, tmp_path: Path) -> None:
        state = LoopState()
        ds = DevelopingSupervisor()
        result = ds.run(state, project=tmp_path, now=datetime.now(timezone.utc))
        assert result.phase == "developing"
        assert result.state_diff == {}
        assert result.log_summary == "no eligible waves to develop"

    def test_dispatches_eligible_wave_with_packet(self, tmp_path: Path) -> None:
        packet_dir = tmp_path / "coord" / "packets" / "wave-001"
        packet_dir.mkdir(parents=True)
        (packet_dir / "packet.md").write_text("# packet", encoding="utf-8")

        state = LoopState(
            wave_plan=[WaveEntry(id="wave-001", name="Test Wave", status="queued")]
        )
        ds = DevelopingSupervisor()

        with patch("harness.loops.supervisors.subprocess.Popen") as mock_popen:
            result = ds.run(state, project=tmp_path, now=datetime.now(timezone.utc))

        assert result.phase == "developing"
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "xaxiu-swarm"
        assert "dispatch" in cmd
        assert str(packet_dir / "packet.md") in cmd
        assert result.state_diff["active_dispatches"]
        assert any(
            d["wave_id"] == "wave-001" for d in result.state_diff["active_dispatches"]
        )
        plan = result.state_diff["wave_plan"]
        assert any(w["id"] == "wave-001" and w["status"] == "in_progress" for w in plan)

    def test_no_double_dispatch_when_active(self, tmp_path: Path) -> None:
        state = LoopState(
            active_dispatches=[
                ActiveDispatch(
                    task_id="t1",
                    packet="p",
                    engine="kimi",
                    dispatched_at="2026-01-01T00:00:00Z",
                    phase="developing",
                )
            ],
            wave_plan=[WaveEntry(id="wave-001", name="Test Wave", status="queued")],
        )
        ds = DevelopingSupervisor()
        result = ds.run(state, project=tmp_path, now=datetime.now(timezone.utc))
        assert result.phase == "developing"
        assert result.state_diff == {}
        assert "already in flight" in result.log_summary

    def test_skips_wave_when_deps_not_met(self, tmp_path: Path) -> None:
        state = LoopState(
            wave_plan=[
                WaveEntry(id="wave-001", name="A", status="done"),
                WaveEntry(
                    id="wave-002",
                    name="B",
                    status="queued",
                    depends_on=["wave-001", "wave-999"],
                ),
            ]
        )
        ds = DevelopingSupervisor()
        result = ds.run(state, project=tmp_path, now=datetime.now(timezone.utc))
        assert result.phase == "developing"
        assert result.state_diff == {}
        assert "no eligible waves" in result.log_summary


# ---------------------------------------------------------------------------
# IntegratingSupervisor
# ---------------------------------------------------------------------------


class TestIntegratingSupervisor:
    def test_no_commit_when_auto_commit_disabled(self, tmp_path: Path) -> None:
        state = LoopState(
            phase_cursors={"integrating": {"pending_merges": [{"wave_id": "w1"}]}},
            wave_plan=[WaveEntry(id="w1", name="W1", status="in_progress")],
        )
        isup = IntegratingSupervisor()

        with patch("harness.loops.supervisors.subprocess.run") as mock_run:

            def side_effect(cmd, **kwargs):
                if cmd[:2] == ["git", "diff"]:
                    return MagicMock(returncode=0, stdout="1 file changed\n", stderr="")
                if cmd[:3] == ["python", "-m", "pytest"]:
                    return MagicMock(returncode=0, stdout="1 passed\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect
            result = isup.run(state, project=tmp_path, now=datetime.now(timezone.utc))

        commit_calls = [
            c for c in mock_run.call_args_list if c[0][0][:2] == ["git", "commit"]
        ]
        assert len(commit_calls) == 0
        # Wave is still marked done even when auto-commit is off
        assert result.state_diff.get("wave_plan") is not None
        assert any(
            w["id"] == "w1" and w["status"] == "done"
            for w in result.state_diff["wave_plan"]
        )

    def test_commits_when_auto_commit_enabled(self, tmp_path: Path) -> None:
        state = LoopState(
            phase_cursors={"integrating": {"pending_merges": [{"wave_id": "w1"}]}},
            wave_plan=[WaveEntry(id="w1", name="W1", status="in_progress")],
        )
        isup = IntegratingSupervisor()

        with patch("harness.loops.supervisors.subprocess.run") as mock_run, patch.dict(
            os.environ, {"HARNESS_ALLOW_AUTO_COMMIT": "true"}
        ):

            def side_effect(cmd, **kwargs):
                if cmd[:2] == ["git", "diff"]:
                    return MagicMock(returncode=0, stdout="1 file changed\n", stderr="")
                if cmd[:3] == ["python", "-m", "pytest"]:
                    return MagicMock(returncode=0, stdout="1 passed\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect
            result = isup.run(state, project=tmp_path, now=datetime.now(timezone.utc))

        commit_calls = [
            c for c in mock_run.call_args_list if c[0][0][:2] == ["git", "commit"]
        ]
        add_calls = [
            c for c in mock_run.call_args_list if c[0][0][:2] == ["git", "add"]
        ]
        assert len(add_calls) == 1
        assert len(commit_calls) == 1
        assert "w1" in commit_calls[0][0][0][3]
        assert result.state_diff.get("wave_plan") is not None

    def test_skips_blocked_merge(self, tmp_path: Path) -> None:
        state = LoopState(
            phase_cursors={
                "integrating": {
                    "pending_merges": [{"wave_id": "w1", "block_commit": True}]
                }
            },
            wave_plan=[WaveEntry(id="w1", name="W1", status="in_progress")],
        )
        isup = IntegratingSupervisor()

        with patch("harness.loops.supervisors.subprocess.run") as mock_run:
            result = isup.run(state, project=tmp_path, now=datetime.now(timezone.utc))

        # No validation commands should run for blocked entries
        assert not any(c[0][0][0] == "git" for c in mock_run.call_args_list)
        assert not any(
            c[0][0][:3] == ["python", "-m", "pytest"] for c in mock_run.call_args_list
        )
        assert result.state_diff == {}
        assert "no merges processed" in result.log_summary

    def test_regression_no_commit(self, tmp_path: Path) -> None:
        state = LoopState(
            phase_cursors={"integrating": {"pending_merges": [{"wave_id": "w1"}]}},
            wave_plan=[WaveEntry(id="w1", name="W1", status="in_progress")],
        )
        isup = IntegratingSupervisor()

        with patch("harness.loops.supervisors.subprocess.run") as mock_run, patch.dict(
            os.environ, {"HARNESS_ALLOW_AUTO_COMMIT": "true"}
        ):

            def side_effect(cmd, **kwargs):
                if cmd[:2] == ["git", "diff"]:
                    return MagicMock(returncode=0, stdout="1 file changed\n", stderr="")
                if cmd[:3] == ["python", "-m", "pytest"]:
                    return MagicMock(returncode=1, stdout="1 failed\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect
            result = isup.run(state, project=tmp_path, now=datetime.now(timezone.utc))

        commit_calls = [
            c for c in mock_run.call_args_list if c[0][0][:2] == ["git", "commit"]
        ]
        assert len(commit_calls) == 0
        assert result.state_diff == {}
        assert "no merges processed" in result.log_summary


# ---------------------------------------------------------------------------
# CreativitySupervisor
# ---------------------------------------------------------------------------


class TestCreativitySupervisor:
    def test_claude_in_session_noop(self, tmp_path: Path) -> None:
        state = LoopState()
        cs = CreativitySupervisor(engine="claude-in-session")
        now = datetime.now(timezone.utc)
        result = cs.run(state, project=tmp_path, now=now)
        assert result.phase == "creativity"
        assert result.state_diff == {}
        assert "claude-in-session" in result.log_summary or "external engine" in result.log_summary

    def test_swarm_kimi_queues_top_idea(self, tmp_path: Path) -> None:
        (tmp_path / "state").mkdir()
        state = LoopState()
        cs = CreativitySupervisor(engine="swarm/kimi")
        now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
        ideas = [
            {"id": "idea-20260520-a", "title": "A", "strategic_score": 70},
            {"id": "idea-20260520-b", "title": "B", "strategic_score": 80},
        ]
        dispatch_result = DispatchResult(
            success=True,
            engine_used="swarm/kimi",
            fallback_chain=["swarm/kimi"],
            text=json.dumps(ideas),
            error=None,
            dispatch_id="uuid-1",
        )
        with patch("harness.engines.dispatcher.dispatch_packet", return_value=dispatch_result):
            result = cs.run(state, project=tmp_path, now=now)
        assert result.phase == "creativity"
        assert result.escalation is None
        queue = result.state_diff["phase_cursors.creativity.queue"]
        assert len(queue) == 1
        assert queue[0]["id"] == "idea-20260520-b"
        assert result.write_set == ["phase_cursors.creativity"]

    def test_swarm_kimi_below_threshold_no_queue(self, tmp_path: Path) -> None:
        (tmp_path / "state").mkdir()
        state = LoopState()
        cs = CreativitySupervisor(engine="swarm/kimi")
        now = datetime.now(timezone.utc)
        ideas = [{"id": "idea-20260520-c", "title": "C", "strategic_score": 40}]
        dispatch_result = DispatchResult(
            success=True,
            engine_used="swarm/kimi",
            fallback_chain=["swarm/kimi"],
            text=json.dumps(ideas),
            error=None,
            dispatch_id="uuid-2",
        )
        with patch("harness.engines.dispatcher.dispatch_packet", return_value=dispatch_result):
            result = cs.run(state, project=tmp_path, now=now)
        assert result.state_diff == {}
        assert "below threshold 60" in result.log_summary

    def test_swarm_kimi_dispatch_failure_escalation(self, tmp_path: Path) -> None:
        (tmp_path / "state").mkdir()
        state = LoopState()
        cs = CreativitySupervisor(engine="swarm/kimi")
        now = datetime.now(timezone.utc)
        dispatch_result = DispatchResult(
            success=False,
            engine_used="swarm/kimi",
            fallback_chain=["swarm/kimi"],
            text="",
            error="connection timeout",
            dispatch_id="uuid-3",
        )
        with patch("harness.engines.dispatcher.dispatch_packet", return_value=dispatch_result):
            result = cs.run(state, project=tmp_path, now=now)
        assert result.escalation is not None
        assert result.escalation["level"] == "L3"
        assert "E_ENGINE_FAILURE" in result.escalation["tag"]
        assert result.state_diff == {}

    def test_swarm_kimi_malformed_json_graceful(self, tmp_path: Path) -> None:
        (tmp_path / "state").mkdir()
        state = LoopState()
        cs = CreativitySupervisor(engine="swarm/kimi")
        now = datetime.now(timezone.utc)
        dispatch_result = DispatchResult(
            success=True,
            engine_used="swarm/kimi",
            fallback_chain=["swarm/kimi"],
            text="not json at all",
            error=None,
            dispatch_id="uuid-4",
        )
        with patch("harness.engines.dispatcher.dispatch_packet", return_value=dispatch_result):
            result = cs.run(state, project=tmp_path, now=now)
        assert result.state_diff == {}
        assert "no valid ideas parsed" in result.log_summary

    def test_write_set_contains_phase_cursors_creativity(self, tmp_path: Path) -> None:
        (tmp_path / "state").mkdir()
        state = LoopState()
        cs = CreativitySupervisor(engine="swarm/kimi")
        now = datetime.now(timezone.utc)
        ideas = [{"id": "idea-20260520-d", "title": "D", "strategic_score": 90}]
        dispatch_result = DispatchResult(
            success=True,
            engine_used="swarm/kimi",
            fallback_chain=["swarm/kimi"],
            text=json.dumps(ideas),
            error=None,
            dispatch_id="uuid-5",
        )
        with patch("harness.engines.dispatcher.dispatch_packet", return_value=dispatch_result):
            result = cs.run(state, project=tmp_path, now=now)
        assert "phase_cursors.creativity" in result.write_set
