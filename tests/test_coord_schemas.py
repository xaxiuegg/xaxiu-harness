"""Tests for harness.coord.schemas Pydantic models."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from harness.coord.schemas import (
    Escalation,
    IntegratorStatus,
    RunState,
    RunStateLiteral,
    TestSummary,
    WavePlan,
    WorkerResult,
    WorkerStateLiteral,
    WorkerStatus,
    WorkerStep,
    WorkerTask,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_step() -> dict[str, Any]:
    return {
        "step_id": "step-1",
        "kind": "edit",
        "instruction": "Change foo to bar",
        "target_files": ["src/foo.py"],
        "expected_diff_lines": 5,
        "required_tests": ["tests/test_foo.py"],
    }


def _valid_task() -> dict[str, Any]:
    return {
        "worker_id": "worker-1",
        "title": "Fix bug",
        "description": "Fix the off-by-one error",
        "read_set": ["src/foo.py"],
        "write_set": ["src/foo.py"],
        "test_set": ["tests/test_foo.py"],
        "depends_on": [],
        "steps": [_valid_step()],
        "estimated_kimi_minutes": 10,
        "max_context_tokens": 30000,
    }


def _valid_plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": "20260520T220000-ab12",
        "spec_path": "spec.md",
        "created_at": "2026-05-20T22:00:00+00:00",
        "planner_engine": "kimi",
        "planner_model": "kimi-latest",
        "tasks": [_valid_task()],
        "integration_strategy": "squash",
        "notes": "",
    }


def _valid_test_summary() -> dict[str, Any]:
    return {"ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2}


def _valid_worker_result() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "worker_id": "worker-1",
        "run_id": "20260520T220000-ab12",
        "state": "completed",
        "started_at": "2026-05-20T22:00:00+00:00",
        "finished_at": "2026-05-20T22:10:00+00:00",
        "steps_completed": ["step-1"],
        "files_modified": ["src/foo.py"],
        "test_summary": _valid_test_summary(),
        "commit_sha": "a1b2c3d",
        "error_tag": None,
        "diagnostic": "",
        "tokens_used": 100,
        "elapsed_seconds": 600,
    }


# ---------------------------------------------------------------------------
# WavePlan validation
# ---------------------------------------------------------------------------

def test_waveplan_minimal_valid() -> None:
    plan = WavePlan.model_validate(_valid_plan())
    assert plan.run_id == "20260520T220000-ab12"
    assert plan.schema_version == 1


def test_waveplan_rejects_missing_run_id() -> None:
    data = _valid_plan()
    del data["run_id"]
    with pytest.raises(ValidationError):
        WavePlan.model_validate(data)


def test_waveplan_rejects_invalid_run_id_pattern() -> None:
    data = _valid_plan()
    data["run_id"] = "bad-run-id"
    with pytest.raises(ValidationError):
        WavePlan.model_validate(data)


def test_waveplan_rejects_zero_tasks() -> None:
    data = _valid_plan()
    data["tasks"] = []
    with pytest.raises(ValidationError):
        WavePlan.model_validate(data)


def test_waveplan_rejects_too_many_tasks() -> None:
    data = _valid_plan()
    data["tasks"] = [_valid_task() for _ in range(25)]
    with pytest.raises(ValidationError):
        WavePlan.model_validate(data)


def test_waveplan_rejects_extra_fields() -> None:
    data = _valid_plan()
    data["unexpected"] = "value"
    with pytest.raises(ValidationError):
        WavePlan.model_validate(data)


def test_waveplan_roundtrip_json() -> None:
    original = WavePlan.model_validate(_valid_plan())
    dumped = original.model_dump_json()
    restored = WavePlan.model_validate_json(dumped)
    assert restored.run_id == original.run_id
    assert restored.tasks[0].worker_id == original.tasks[0].worker_id


# ---------------------------------------------------------------------------
# WorkerTask validation
# ---------------------------------------------------------------------------

def test_workertask_rejects_bad_worker_id_format() -> None:
    data = _valid_task()
    data["worker_id"] = "bad-id"
    with pytest.raises(ValidationError):
        WorkerTask.model_validate(data)


def test_workertask_rejects_missing_required_fields() -> None:
    for field in ("worker_id", "title", "description"):
        data = _valid_task()
        del data[field]
        with pytest.raises(ValidationError):
            WorkerTask.model_validate(data)


def test_workertask_rejects_oversized_write_set() -> None:
    data = _valid_task()
    data["write_set"] = [f"file{i}.py" for i in range(21)]
    with pytest.raises(ValidationError):
        WorkerTask.model_validate(data)


def test_workertask_rejects_extra_fields() -> None:
    data = _valid_task()
    data["foo"] = "bar"
    with pytest.raises(ValidationError):
        WorkerTask.model_validate(data)


def test_workertask_roundtrip_json() -> None:
    original = WorkerTask.model_validate(_valid_task())
    dumped = original.model_dump_json()
    restored = WorkerTask.model_validate_json(dumped)
    assert restored.worker_id == original.worker_id


# ---------------------------------------------------------------------------
# WorkerStep validation
# ---------------------------------------------------------------------------

def test_workerstep_rejects_unknown_kind() -> None:
    data = _valid_step()
    data["kind"] = "fly"
    with pytest.raises(ValidationError):
        WorkerStep.model_validate(data)


def test_workerstep_rejects_oversized_instruction() -> None:
    data = _valid_step()
    data["instruction"] = "x" * 4001
    with pytest.raises(ValidationError):
        WorkerStep.model_validate(data)


def test_workerstep_rejects_extra_fields() -> None:
    data = _valid_step()
    data["bonus"] = 123
    with pytest.raises(ValidationError):
        WorkerStep.model_validate(data)


def test_workerstep_roundtrip_json() -> None:
    original = WorkerStep.model_validate(_valid_step())
    dumped = original.model_dump_json()
    restored = WorkerStep.model_validate_json(dumped)
    assert restored.step_id == original.step_id


# ---------------------------------------------------------------------------
# WorkerResult validation
# ---------------------------------------------------------------------------

def test_workerresult_rejects_bad_commit_sha() -> None:
    data = _valid_worker_result()
    data["commit_sha"] = "g1h2i3j"
    with pytest.raises(ValidationError):
        WorkerResult.model_validate(data)


def test_workerresult_accepts_valid_commit_sha() -> None:
    data = _valid_worker_result()
    data["commit_sha"] = "abc1234"
    result = WorkerResult.model_validate(data)
    assert result.commit_sha == "abc1234"


def test_workerresult_rejects_extra_fields() -> None:
    data = _valid_worker_result()
    data["surprise"] = True
    with pytest.raises(ValidationError):
        WorkerResult.model_validate(data)


def test_workerresult_roundtrip_json() -> None:
    original = WorkerResult.model_validate(_valid_worker_result())
    dumped = original.model_dump_json()
    restored = WorkerResult.model_validate_json(dumped)
    assert restored.worker_id == original.worker_id


# ---------------------------------------------------------------------------
# Auxiliary schema validation
# ---------------------------------------------------------------------------

def test_testsummary_roundtrip_json() -> None:
    original = TestSummary.model_validate(_valid_test_summary())
    dumped = original.model_dump_json()
    restored = TestSummary.model_validate_json(dumped)
    assert restored.ran == original.ran


def test_workerstatus_rejects_extra_fields() -> None:
    data = {
        "worker_id": "worker-1",
        "state": "pending",
    }
    data["extra"] = "nope"
    with pytest.raises(ValidationError):
        WorkerStatus.model_validate(data)


def test_integratorstatus_rejects_extra_fields() -> None:
    data = {"state": "pending"}
    data["extra"] = "nope"
    with pytest.raises(ValidationError):
        IntegratorStatus.model_validate(data)


def test_escalation_rejects_extra_fields() -> None:
    data = {
        "id": "esc-1",
        "level": "L3",
        "tag": "validation-fail",
        "raised_at": "2026-05-20T22:00:00+00:00",
    }
    data["extra"] = "nope"
    with pytest.raises(ValidationError):
        Escalation.model_validate(data)


def test_runstate_rejects_extra_fields() -> None:
    data = {
        "schema_version": 1,
        "run_id": "20260520T220000-ab12",
        "spec_path": "spec.md",
        "state": "running",
        "plan_path": "plan.json",
        "started_at": "2026-05-20T22:00:00+00:00",
        "last_tick_at": "2026-05-20T22:01:00+00:00",
    }
    data["extra"] = "nope"
    with pytest.raises(ValidationError):
        RunState.model_validate(data)


def test_runstate_roundtrip_json() -> None:
    data = {
        "schema_version": 1,
        "run_id": "20260520T220000-ab12",
        "spec_path": "spec.md",
        "state": "running",
        "plan_path": "plan.json",
        "started_at": "2026-05-20T22:00:00+00:00",
        "last_tick_at": "2026-05-20T22:01:00+00:00",
        "workers": {
            "worker-1": {
                "worker_id": "worker-1",
                "state": "in_progress",
            }
        },
        "integrator_status": None,
        "escalations": [],
    }
    original = RunState.model_validate(data)
    dumped = original.model_dump_json()
    restored = RunState.model_validate_json(dumped)
    assert restored.run_id == original.run_id
    assert restored.workers["worker-1"].state == WorkerStateLiteral.IN_PROGRESS
