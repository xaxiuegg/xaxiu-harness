"""Integration tests for the 4 inline-shipped wiring rows:

- WIRE-STALL-DETECT (Coordinator.tick calls detect_stalled_workers)
- WIRE-AUTOLINT (planner.plan auto-lints spec)
- WIRE-PROVENANCE-VERIFY (dispatch_packet auto-verifies)
- WIRE-FLAP-ESCALATION (circuit-flap writes L4 file)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# WIRE-AUTOLINT
# ---------------------------------------------------------------------------


def test_planner_refuses_empty_spec(tmp_path: Path) -> None:
    """plan() raises ValueError when the spec fails lint preflight."""
    from harness.coord.planner import plan
    bad = tmp_path / "spec.md"
    bad.write_text("", encoding="utf-8")  # E_EMPTY
    with pytest.raises(ValueError) as exc:
        plan(bad, engine="mock")
    assert "spec lint failed" in str(exc.value)
    assert "E_EMPTY" in str(exc.value)


def test_planner_skip_lint_bypasses(tmp_path: Path) -> None:
    """skip_lint=True bypasses the lint preflight (verified by the body parser)."""
    from harness.coord import planner as planner_module
    bad = tmp_path / "spec.md"
    bad.write_text("", encoding="utf-8")

    fake_result = MagicMock(success=False, error="adapter_not_found")
    # Planner does `from harness.engines.dispatcher import dispatch_packet`
    # inside the function, so we have to patch it at the source module.
    with patch("harness.engines.dispatcher.dispatch_packet", return_value=fake_result):
        with pytest.raises(Exception) as exc:
            planner_module.plan(bad, engine="mock", skip_lint=True, max_retries=0)
    assert "spec lint failed" not in str(exc.value)


def test_planner_passes_clean_spec(tmp_path: Path) -> None:
    """A clean spec gets through lint; dispatch is then called."""
    from harness.coord import planner as planner_module
    good = tmp_path / "spec.md"
    good.write_text(
        "# spec\n\nAdd a /health endpoint.\n\n"
        "## Acceptance\n- /health returns 200\n",
        encoding="utf-8",
    )
    called = {"dispatch": False}

    def fake_dispatch(**kw):
        called["dispatch"] = True
        return MagicMock(
            success=True,
            text='{"schema_version":1,"run_id":"20260521T000000-aabb",'
                 '"spec_path":"x","created_at":"x","planner_engine":"mock",'
                 '"tasks":[{"worker_id":"worker-1","title":"t","description":"d",'
                 '"steps":[{"step_id":"s1","kind":"edit","instruction":"x",'
                 '"target_files":["x"],"expected_diff_lines":1}]}]}',
            error=None,
        )

    with patch("harness.engines.dispatcher.dispatch_packet", side_effect=fake_dispatch):
        planner_module.plan(good, engine="mock", max_retries=0)
    assert called["dispatch"] is True


# ---------------------------------------------------------------------------
# WIRE-PROVENANCE-VERIFY
# ---------------------------------------------------------------------------


def test_dispatcher_blocks_tampered_packet_when_registered(tmp_path: Path, monkeypatch) -> None:
    """dispatch_packet refuses with provenance_mismatch when the SHA doesn't match the registration."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_ALLOW_UNSAFE_PACKETS", raising=False)
    from harness.engines.dispatcher import dispatch_packet
    from harness.coord.provenance import register

    spec = tmp_path / "spec.md"
    spec.write_text("# original\n", encoding="utf-8")
    register(spec)  # writes coord/spec_provenance.jsonl
    # Tamper the spec
    spec.write_text("# tampered\n", encoding="utf-8")

    with patch("harness.engines.dispatcher.load_project_adapter") as mock_load:
        mock_load.return_value = MagicMock(routing_rules=[])
        result = dispatch_packet(project="valid-project", packet_path=str(spec))

    assert result.success is False
    assert result.error is not None
    assert "packet_provenance_mismatch" in result.error


def test_dispatcher_allows_unregistered_packet(tmp_path: Path, monkeypatch) -> None:
    """An unregistered packet still dispatches (provenance is opt-in)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_ALLOW_UNSAFE_PACKETS", raising=False)
    from harness.engines.dispatcher import dispatch_packet

    spec = tmp_path / "spec.md"
    spec.write_text("# new spec\n", encoding="utf-8")
    # NOTE: no register() call

    # Provenance log doesn't even exist, so verify() is skipped entirely.
    with patch("harness.engines.dispatcher.load_project_adapter") as mock_load:
        mock_load.return_value = MagicMock(routing_rules=[])
        result = dispatch_packet(project="valid-project", packet_path=str(spec))
    if result.error:
        assert "packet_provenance_mismatch" not in result.error


# ---------------------------------------------------------------------------
# WIRE-FLAP-ESCALATION
# ---------------------------------------------------------------------------


def test_flap_writes_escalation_file(tmp_path: Path, monkeypatch) -> None:
    """When AUTO-QUARANTINE-KEY fires, an L4 file lands in coord/observer/escalations/."""
    monkeypatch.chdir(tmp_path)
    from harness.proxy.circuit import transition
    from harness.proxy.state import CircuitState, KeyState

    base = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    # 3 trips inside the 60-min window → auto-quarantine + escalation
    for i in range(3):
        state.consecutive_failures = 0
        state.circuit_state = CircuitState.CLOSED
        for _ in range(3):
            state = transition(state, "server_error", now=base + timedelta(minutes=15 * i))

    assert state.permanent is True
    esc_dir = tmp_path / "coord" / "observer" / "escalations"
    files = list(esc_dir.glob("flap_k1_*.json"))
    assert len(files) >= 1
    record = json.loads(files[0].read_text(encoding="utf-8"))
    assert record["level"] == "L4"
    assert record["key_alias"] == "k1"
    assert "auto-quarantined" in record["diagnostic"]


def test_no_flap_no_escalation_file(tmp_path: Path, monkeypatch) -> None:
    """Single circuit trip ⇒ no escalation file (only on flap detection)."""
    monkeypatch.chdir(tmp_path)
    from harness.proxy.circuit import transition
    from harness.proxy.state import KeyState

    base = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = KeyState(key_alias="k1")
    for _ in range(3):
        state = transition(state, "server_error", now=base)
    assert state.permanent is False
    esc_dir = tmp_path / "coord" / "observer" / "escalations"
    assert not esc_dir.exists() or not list(esc_dir.glob("flap_*.json"))


# ---------------------------------------------------------------------------
# WIRE-STALL-DETECT
# ---------------------------------------------------------------------------


def test_coordinator_tick_escalates_on_stall(tmp_path: Path, monkeypatch) -> None:
    """When detect_stalled_workers returns a worker, an L4 stall escalation lands in run_state."""
    from harness.coord.coordinator import Coordinator
    from harness.coord.run_state import write_run_state, read_run_state
    from harness.coord.schemas import (
        IntegratorStatus, RunState, RunStateLiteral, WorkerStatus, WorkerStateLiteral, WavePlan, WorkerTask, WorkerStep,
    )

    run_id = "20260521T010101-aabb"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    plan = WavePlan(
        run_id=run_id, spec_path="s.md", created_at="2026-05-21T00:00:00+00:00",
        planner_engine="mock",
        tasks=[WorkerTask(worker_id="worker-1", title="t", description="d",
                          steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                                            target_files=["x"], expected_diff_lines=1)])],
    )
    (run_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
    write_run_state(run_dir / "run_state.json", RunState(
        schema_version=1, run_id=run_id, spec_path="s.md",
        state=RunStateLiteral.RUNNING, plan_path=str(run_dir / "plan.json"),
        started_at="2026-05-21T01:00:00Z", last_tick_at="2026-05-21T01:00:00Z",
        workers={"worker-1": WorkerStatus(worker_id="worker-1",
                                          state=WorkerStateLiteral.IN_PROGRESS)},
        integrator_status=IntegratorStatus(state="pending"),
        escalations=[],
    ))

    coord = Coordinator(run_id=run_id, run_dir=run_dir)
    with patch.object(coord, "launch_workers", return_value={}), \
         patch.object(coord, "poll_workers", return_value={
             "worker-1": WorkerStatus(worker_id="worker-1",
                                      state=WorkerStateLiteral.IN_PROGRESS),
         }), \
         patch("harness.coord.coordinator.detect_stalled_workers",
               return_value=["worker-1"]):
        coord.tick(spec_path=Path("s.md"))

    new_state = read_run_state(run_dir / "run_state.json")
    assert any(e.tag == "stall" and "worker-1" in e.affected_workers
               for e in new_state.escalations)
