"""Tests for harness.coord.worker."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.coord.checkpoint import Checkpoint, read_checkpoint
from harness.coord.worker import run_worker, _run_pytest
from harness.coord.schemas import WorkerTask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_task_dict() -> dict:
    return {
        "worker_id": "worker-1",
        "title": "Fix bug",
        "description": "Fix the off-by-one error",
        "read_set": ["src/foo.py"],
        "write_set": ["src/foo.py"],
        "test_set": ["tests/test_foo.py"],
        "depends_on": [],
        "steps": [
            {
                "step_id": "step-1",
                "kind": "edit",
                "instruction": "Change foo to bar",
                "target_files": ["src/foo.py"],
                "expected_diff_lines": 5,
                "required_tests": [],
            },
            {
                "step_id": "step-2",
                "kind": "test",
                "instruction": "Run tests",
                "target_files": [],
                "expected_diff_lines": 0,
                "required_tests": ["tests/test_foo.py"],
            },
        ],
        "estimated_kimi_minutes": 10,
        "max_context_tokens": 30000,
    }


# ---------------------------------------------------------------------------
# _run_pytest
# ---------------------------------------------------------------------------

def test_run_pytest_empty_test_set_returns_zero_summary() -> None:
    result = _run_pytest([], cwd=Path("."))
    assert result == {"ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0}


# ---------------------------------------------------------------------------
# run_worker — fresh task
# ---------------------------------------------------------------------------

def test_run_worker_fresh_task_creates_initial_checkpoint(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)

    checkpoint_path = run_dir / "checkpoints" / "worker-1.json"
    assert checkpoint_path.exists()
    ckpt = read_checkpoint(checkpoint_path)
    assert ckpt is not None
    assert ckpt.worker_id == "worker-1"
    assert ckpt.state == "completed"
    assert ckpt.last_completed_step_index == 1
    assert ckpt.last_completed_step_id == "step-2"
    assert "src/foo.py" in ckpt.files_modified


def test_run_worker_writes_deliverable_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)

    deliv_path = run_dir / "deliverables" / "worker-1.json"
    assert deliv_path.exists()
    raw = json.loads(deliv_path.read_text(encoding="utf-8"))
    assert raw["worker_id"] == "worker-1"
    assert raw["run_id"] == "20260520T220000-ab12"
    assert raw["state"] == "completed"
    assert raw["error_tag"] is None
    assert raw["steps_completed"] == ["step-1", "step-2"]


def test_run_worker_state_transitions_in_progress_to_completed(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
    }):
        run_worker(task, run_dir, project_root=tmp_path)

    ckpt = read_checkpoint(run_dir / "checkpoints" / "worker-1.json")
    assert ckpt is not None
    assert ckpt.state == "completed"
    assert ckpt.tests_passed is True
    assert ckpt.tests_summary == "5p/0f/0s"


def test_run_worker_state_transitions_to_failed_on_test_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 3, "failed": 2, "skipped": 0, "duration_seconds": 2.0,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)

    ckpt = read_checkpoint(run_dir / "checkpoints" / "worker-1.json")
    assert ckpt is not None
    assert ckpt.state == "failed"
    assert ckpt.tests_passed is False
    assert ckpt.tests_summary == "3p/2f/0s"
    assert result["error_tag"] == "L3.worker.E_TEST_FAILED"


# ---------------------------------------------------------------------------
# run_worker — resume
# ---------------------------------------------------------------------------

def test_run_worker_resumes_from_existing_checkpoint(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    checkpoint_path = run_dir / "checkpoints" / "worker-1.json"
    existing = Checkpoint(
        worker_id="worker-1",
        run_id="20260520T220000-ab12",
        last_completed_step_id="step-1",
        last_completed_step_index=0,
        files_modified=["src/foo.py"],
        state="in_progress",
        updated_at="2026-05-20T21:00:00+00:00",
    )
    from harness.coord.checkpoint import write_checkpoint
    write_checkpoint(checkpoint_path, existing)

    task = _valid_task_dict()

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)

    ckpt = read_checkpoint(checkpoint_path)
    assert ckpt is not None
    assert ckpt.last_completed_step_index == 1  # resumed and finished step-2
    assert ckpt.state == "completed"
    assert result["steps_completed"] == ["step-1", "step-2"]


def test_run_worker_resumes_from_resume_from_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    other_ckpt_path = tmp_path / "backup_ckpt.json"
    existing = Checkpoint(
        worker_id="worker-1",
        run_id="20260520T220000-ab12",
        last_completed_step_id="step-1",
        last_completed_step_index=0,
        files_modified=["src/foo.py"],
        state="in_progress",
        updated_at="2026-05-20T21:00:00+00:00",
    )
    from harness.coord.checkpoint import write_checkpoint
    write_checkpoint(other_ckpt_path, existing)

    task = _valid_task_dict()

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path, resume_from=other_ckpt_path)

    ckpt = read_checkpoint(run_dir / "checkpoints" / "worker-1.json")
    assert ckpt is not None
    assert ckpt.last_completed_step_index == 1


# ---------------------------------------------------------------------------
# run_worker — empty steps / test_set
# ---------------------------------------------------------------------------

def test_run_worker_empty_steps_and_empty_test_set(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()
    task["steps"] = []
    task["test_set"] = []

    result = run_worker(task, run_dir, project_root=tmp_path)

    assert result["state"] == "completed"
    assert result["test_summary"] == {"ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0}
    assert result["steps_completed"] == []
    assert result["error_tag"] is None


# ---------------------------------------------------------------------------
# _run_pytest — subprocess + parsing coverage
# ---------------------------------------------------------------------------

def test_run_pytest_parses_one_passed() -> None:
    mock_proc = MagicMock()
    mock_proc.stdout = "1 passed in 0.01s"
    mock_proc.returncode = 0
    with patch("harness.coord.worker.subprocess.run", return_value=mock_proc):
        result = _run_pytest(["tests/test_foo.py"], cwd=Path("."))
    assert result["ran"] == 1
    assert result["passed"] == 1
    assert result["failed"] == 0
    assert result["skipped"] == 0
    assert result["duration_seconds"] >= 0.0


def test_run_pytest_parses_three_failed() -> None:
    mock_proc = MagicMock()
    mock_proc.stdout = "3 failed in 0.05s"
    mock_proc.returncode = 1
    with patch("harness.coord.worker.subprocess.run", return_value=mock_proc):
        result = _run_pytest(["tests/test_foo.py"], cwd=Path("."))
    assert result["ran"] == 3
    assert result["passed"] == 0
    assert result["failed"] == 3
    assert result["skipped"] == 0


def test_run_pytest_parses_two_skipped() -> None:
    mock_proc = MagicMock()
    mock_proc.stdout = "2 skipped in 0.01s"
    mock_proc.returncode = 0
    with patch("harness.coord.worker.subprocess.run", return_value=mock_proc):
        result = _run_pytest(["tests/test_foo.py"], cwd=Path("."))
    assert result["ran"] == 2
    assert result["passed"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 2


def test_run_pytest_parses_combined_summary() -> None:
    mock_proc = MagicMock()
    mock_proc.stdout = "5 passed, 2 failed, 1 skipped in 0.10s"
    mock_proc.returncode = 1
    with patch("harness.coord.worker.subprocess.run", return_value=mock_proc):
        result = _run_pytest(["tests/test_foo.py"], cwd=Path("."))
    assert result["ran"] == 8
    assert result["passed"] == 5
    assert result["failed"] == 2
    assert result["skipped"] == 1


def test_run_pytest_returns_zeros_on_empty_output() -> None:
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.returncode = 0
    with patch("harness.coord.worker.subprocess.run", return_value=mock_proc):
        result = _run_pytest(["tests/test_foo.py"], cwd=Path("."))
    assert result["ran"] == 0
    assert result["passed"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 0
    assert result["duration_seconds"] >= 0.0


def test_run_pytest_raises_timeout_expired() -> None:
    with patch(
        "harness.coord.worker.subprocess.run",
        side_effect=subprocess.TimeoutExpired("python -m pytest", 300),
    ):
        with pytest.raises(subprocess.TimeoutExpired):
            _run_pytest(["tests/test_foo.py"], cwd=Path("."))


# ---------------------------------------------------------------------------
# run_worker — resume branches
# ---------------------------------------------------------------------------

def test_run_worker_resumes_from_step_two_of_five(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()
    task["steps"] = [
        {
            "step_id": f"step-{i}",
            "kind": "edit",
            "instruction": f"Do {i}",
            "target_files": [f"src/f{i}.py"],
            "expected_diff_lines": 1,
            "required_tests": [],
        }
        for i in range(1, 6)
    ]
    checkpoint_path = run_dir / "checkpoints" / "worker-1.json"
    existing = Checkpoint(
        worker_id="worker-1",
        run_id="20260520T220000-ab12",
        last_completed_step_id="step-2",
        last_completed_step_index=1,
        files_modified=["src/f1.py", "src/f2.py"],
        state="in_progress",
        updated_at="2026-05-20T21:00:00+00:00",
    )
    from harness.coord.checkpoint import write_checkpoint
    write_checkpoint(checkpoint_path, existing)

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)

    ckpt = read_checkpoint(checkpoint_path)
    assert ckpt is not None
    assert ckpt.last_completed_step_index == 4
    assert ckpt.last_completed_step_id == "step-5"
    assert ckpt.state == "completed"
    assert set(ckpt.files_modified or []) == {"src/f1.py", "src/f2.py", "src/f3.py", "src/f4.py", "src/f5.py"}
    assert result["steps_completed"] == ["step-1", "step-2", "step-3", "step-4", "step-5"]


def test_run_worker_resumes_from_completed_checkpoint(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()
    checkpoint_path = run_dir / "checkpoints" / "worker-1.json"
    existing = Checkpoint(
        worker_id="worker-1",
        run_id="20260520T220000-ab12",
        last_completed_step_id="step-2",
        last_completed_step_index=1,
        files_modified=["src/foo.py"],
        state="completed",
        tests_passed=True,
        tests_summary="5p/0f/0s",
        updated_at="2026-05-20T21:00:00+00:00",
    )
    from harness.coord.checkpoint import write_checkpoint
    write_checkpoint(checkpoint_path, existing)

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)

    ckpt = read_checkpoint(checkpoint_path)
    assert ckpt is not None
    assert ckpt.state == "completed"
    assert result["state"] == "completed"
    assert result["steps_completed"] == ["step-1", "step-2"]
    assert result["error_tag"] is None


# ---------------------------------------------------------------------------
# run_worker — error / edge paths
# ---------------------------------------------------------------------------

def test_run_worker_pytest_error_exit_code_two(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    mock_proc = MagicMock()
    mock_proc.stdout = "2 passed, 1 failed in 0.05s"
    mock_proc.returncode = 2

    with patch("harness.coord.worker.subprocess.run", return_value=mock_proc):
        result = run_worker(task, run_dir, project_root=tmp_path)

    assert result["state"] == "failed"
    assert result["error_tag"] == "L3.worker.E_TEST_FAILED"
    ckpt = read_checkpoint(run_dir / "checkpoints" / "worker-1.json")
    assert ckpt is not None
    assert ckpt.state == "failed"
    assert ckpt.tests_summary == "2p/1f/0s"


def test_run_worker_propagates_subprocess_timeout(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    with patch(
        "harness.coord.worker.subprocess.run",
        side_effect=subprocess.TimeoutExpired("python -m pytest", 300),
    ):
        with pytest.raises(subprocess.TimeoutExpired):
            run_worker(task, run_dir, project_root=tmp_path)


def test_run_worker_propagates_file_not_found_for_missing_worktree(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    with patch(
        "harness.coord.worker.subprocess.run",
        side_effect=FileNotFoundError(2, "The system cannot find the file specified"),
    ):
        with pytest.raises(FileNotFoundError):
            run_worker(task, run_dir, project_root=tmp_path)
