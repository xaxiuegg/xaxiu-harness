"""Tests for harness.coord.worker."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from harness.coord.checkpoint import Checkpoint, read_checkpoint
from harness.coord.worker import run_worker, _run_pytest, _build_prompt
from harness.coord.schemas import WorkerTask


# Default engine in worker.run_worker is "swarm/kimi", which shells out to
# xaxiu-swarm + the real Kimi API.  Unit tests must NEVER hit the network,
# so we autouse-patch _dispatch_via_swarm to return a no-op success result.
# Tests that want to assert dispatch behaviour can re-patch inside their
# own `with patch(...)` block.
@pytest.fixture(autouse=True)
def _stub_swarm_dispatch():
    # WIRE-NOOP-DETECT (2026-05-22): worker.run_worker now hard-fails when
    # an edit step's target_files were declared but zero files actually
    # changed.  The stub MUST return a FILE/REPLACE block that creates
    # src/foo.py (the default task fixture's target_files) — otherwise
    # every test using this autouse stub triggers silent_no_op detection.
    stub = SimpleNamespace(
        success=True,
        text=(
            "FILE: src/foo.py\n"
            "<<<<<<< SEARCH\n"
            "=======\n"
            "# stub edit applied by autouse fixture\n"
            ">>>>>>> REPLACE\n"
        ),
        error=None, tokens_used=0, cost_usd=0.0,
    )
    with patch("harness.coord.worker._dispatch_via_swarm", return_value=stub):
        yield


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

    # WIRE-NOOP-DETECT (2026-05-22): override the autouse stub so each
    # step's dispatch returns a FILE/REPLACE that creates the step's
    # actual target file (src/fN.py).  Counter-based since the packet
    # text doesn't contain the bare target path in a stable form.
    _step_counter = {"n": 2}  # resume starts at step-3 (index 2)

    def _per_step_stub(packet_path, engine, wt_path):
        _step_counter["n"] += 1
        n = _step_counter["n"]
        return SimpleNamespace(
            success=True,
            text=f"FILE: src/f{n}.py\n<<<<<<< SEARCH\n=======\n# step {n}\n>>>>>>> REPLACE\n",
            error=None, tokens_used=0, cost_usd=0.0,
        )

    with patch("harness.coord.worker._dispatch_via_swarm", side_effect=_per_step_stub):
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


# ---------------------------------------------------------------------------
# Engine dispatch + edit application
# ---------------------------------------------------------------------------

def test_run_worker_calls_swarm_dispatch_for_edit_step_default_engine(tmp_path: Path) -> None:
    """Default engine 'swarm/kimi' routes through _dispatch_via_swarm, not in-process dispatch_packet."""
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()
    src_file = tmp_path / "src" / "foo.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("old content\n", encoding="utf-8")
    wt = tmp_path / ".harness" / "worktrees" / run_dir.name / "worker-1"
    wt.mkdir(parents=True)

    swarm_result = SimpleNamespace(
        success=True, text="", error=None, tokens_used=0, cost_usd=0.0,
    )
    # Override the autouse stub so we can assert the call shape
    with patch("harness.coord.worker._dispatch_via_swarm",
               return_value=swarm_result) as mock_swarm:
        with patch("harness.coord.worker._run_pytest", return_value={
            "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
        }):
            run_worker(task, run_dir, project_root=tmp_path)

    # 2 steps × 1 edit each → 2 swarm dispatches in default flow
    assert mock_swarm.call_count >= 1
    # Positional args: (packet_path, engine, wt_path)
    first_call = mock_swarm.call_args_list[0]
    assert first_call.args[1] == "swarm/kimi"


def test_run_worker_applies_file_edits_from_swarm_response(tmp_path: Path) -> None:
    """When _dispatch_via_swarm returns FILE/REPLACE text, worker applies edits."""
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()
    src_file = tmp_path / "src" / "foo.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("old content\n", encoding="utf-8")
    wt = tmp_path / ".harness" / "worktrees" / run_dir.name / "worker-1"
    wt.mkdir(parents=True)
    wt_src = wt / "src" / "foo.py"
    wt_src.parent.mkdir(parents=True)
    wt_src.write_text("old content\n", encoding="utf-8")

    swarm_result = SimpleNamespace(
        success=True,
        text=(
            "FILE: src/foo.py\n"
            "<<<<<<< SEARCH\n"
            "old content\n"
            "=======\n"
            "new content\n"
            ">>>>>>> REPLACE\n"
        ),
        error=None, tokens_used=0, cost_usd=0.0,
    )
    with patch("harness.coord.worker._dispatch_via_swarm", return_value=swarm_result):
        with patch("harness.coord.worker._run_pytest", return_value={
            "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
        }):
            result = run_worker(task, run_dir, project_root=tmp_path)

    assert wt_src.read_text(encoding="utf-8") == "new content\n"
    assert "src/foo.py" in result["files_modified"]


def test_run_worker_captures_commit_sha_after_git_commit(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()
    wt = tmp_path / ".harness" / "worktrees" / run_dir.name / "worker-1"
    wt.mkdir(parents=True)

    with patch("harness.engines.dispatcher.dispatch_packet", return_value=MagicMock(success=True, text="")):
        with patch("harness.coord.worker._git_commit", return_value="abc1234def5678"):
            with patch("harness.coord.worker._run_pytest", return_value={
                "ran": 5, "passed": 5, "failed": 0, "skipped": 0, "duration_seconds": 1.2,
            }):
                result = run_worker(task, run_dir, project_root=tmp_path)

    assert result["commit_sha"] == "abc1234def5678"
    ckpt = read_checkpoint(run_dir / "checkpoints" / "worker-1.json")
    assert ckpt is not None
    assert ckpt.commit_sha == "abc1234def5678"


# ---------------------------------------------------------------------------
# FILE/REPLACE parser
# ---------------------------------------------------------------------------

def test_parse_file_edits_extracts_single_block() -> None:
    text = (
        "FILE: src/foo.py\n"
        "<<<<<<< SEARCH\n"
        "old\n"
        "=======\n"
        "new\n"
        ">>>>>>> REPLACE\n"
    )
    edits = __import__("harness.coord.worker", fromlist=["_parse_file_edits"])._parse_file_edits(text)
    from harness.coord.worker import _parse_file_edits
    edits = _parse_file_edits(text)
    assert len(edits) == 1
    assert edits[0] == ("src/foo.py", "old", "new")


def test_parse_file_edits_extracts_multiple_blocks() -> None:
    text = (
        "FILE: a.py\n"
        "<<<<<<< SEARCH\n"
        "x\n"
        "=======\n"
        "y\n"
        ">>>>>>> REPLACE\n"
        "\n"
        "FILE: b.py\n"
        "<<<<<<< SEARCH\n"
        "1\n"
        "=======\n"
        "2\n"
        ">>>>>>> REPLACE\n"
    )
    from harness.coord.worker import _parse_file_edits
    edits = _parse_file_edits(text)
    assert len(edits) == 2
    assert edits[0] == ("a.py", "x", "y")
    assert edits[1] == ("b.py", "1", "2")


def test_apply_file_edits_creates_missing_file(tmp_path: Path) -> None:
    from harness.coord.worker import _apply_file_edits
    edits = [("new_dir/new_file.py", "", "hello")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["new_dir/new_file.py"]
    assert (tmp_path / "new_dir" / "new_file.py").read_text(encoding="utf-8") == "hello"


def test_apply_file_edits_skips_when_search_not_found(tmp_path: Path) -> None:
    from harness.coord.worker import _apply_file_edits
    f = tmp_path / "a.py"
    f.write_text("content\n", encoding="utf-8")
    edits = [("a.py", "nonexistent", "replacement")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == []
    assert f.read_text(encoding="utf-8") == "content\n"


# ---------------------------------------------------------------------------
# WIRE-DISPATCH-HARDFAIL (2026-05-22) — D6
# ---------------------------------------------------------------------------

def test_dispatch_via_swarm_raises_worktree_missing(tmp_path: Path, monkeypatch) -> None:
    """_dispatch_via_swarm must hard-fail when the worktree path does not exist."""
    # The autouse _stub_swarm_dispatch fixture replaces the symbol;
    # re-import the original via __wrapped__ / module attribute lookup
    # is unreliable, so resolve the function freshly from the module.
    import importlib
    worker_mod = importlib.import_module("harness.coord.worker")
    # Capture the *real* function before any autouse patch wraps it for
    # this test by reading it from a fresh module reload.
    importlib.reload(worker_mod)
    real_dispatch = worker_mod._dispatch_via_swarm

    from harness.errors import WorktreeMissing

    packet = tmp_path / "packet.md"
    packet.write_text("hello", encoding="utf-8")
    nonexistent_wt = tmp_path / "does_not_exist"

    with pytest.raises(WorktreeMissing) as exc_info:
        real_dispatch(packet, "swarm/kimi", nonexistent_wt)

    err = exc_info.value
    assert err.tag() == "L4.dispatch.E_MISSING_WORKTREE"
    assert str(nonexistent_wt) in err.message
    assert err.context.get("engine") == "swarm/kimi"


def test_dispatch_via_swarm_does_not_run_subprocess_when_worktree_missing(tmp_path: Path) -> None:
    """The most important safety bit: no subprocess.run at all if worktree missing."""
    import importlib
    worker_mod = importlib.import_module("harness.coord.worker")
    importlib.reload(worker_mod)
    real_dispatch = worker_mod._dispatch_via_swarm
    from harness.errors import WorktreeMissing

    packet = tmp_path / "packet.md"
    packet.write_text("hello", encoding="utf-8")
    nonexistent_wt = tmp_path / "ghost"

    with patch.object(worker_mod.subprocess, "run") as mock_run:
        with pytest.raises(WorktreeMissing):
            real_dispatch(packet, "swarm/kimi", nonexistent_wt)
        mock_run.assert_not_called()


def test_dispatch_via_swarm_routes_mimo_through_direct_http(tmp_path: Path) -> None:
    """WIRE-SWARM-DIRECT-HTTP (2026-05-22): swarm/mimo bypasses xaxiu-swarm
    subprocess and calls dispatch_packet directly because the swarm CLI
    has no mimo backend.  Operator-facing identifier stays uniform but
    the runtime path is in-process."""
    import importlib
    worker_mod = importlib.import_module("harness.coord.worker")
    importlib.reload(worker_mod)
    real_dispatch = worker_mod._dispatch_via_swarm

    packet = tmp_path / "packet.md"
    packet.write_text("hi", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()

    fake = SimpleNamespace(
        success=True, text="FILE/REPLACE\n...\n", error=None,
        tokens_used=100, cost_usd=0.0,
    )
    with patch("harness.engines.dispatcher.dispatch_packet",
               return_value=fake) as mock_dispatch:
        with patch.object(worker_mod.subprocess, "run") as mock_subproc:
            result = real_dispatch(packet, "swarm/mimo", wt)
            # xaxiu-swarm subprocess MUST NOT be invoked for mimo
            mock_subproc.assert_not_called()
            # dispatch_packet was called with force_engine='mimo' (bare backend)
            mock_dispatch.assert_called_once()
            kwargs = mock_dispatch.call_args.kwargs
            assert kwargs["force_engine"] == "mimo"
            assert kwargs["project"] == "harness-worker"
            # W6-A1-4 2026-05-23: worker prompts include legitimate harness
            # source (W6-A1-3 fix pre-loads write_set files), which can
            # contain patterns like `list_secrets(` that trip the
            # dispatch_packet injection scanner.  Worker must mark the
            # call as trusted_source so the scanner skips it.
            assert kwargs.get("trusted_source") is True, (
                "worker.py must pass trusted_source=True to dispatch_packet "
                "or the injection scanner will block prompts containing "
                "legitimate harness code patterns"
            )

    assert result.success is True
    assert result.text.startswith("FILE/REPLACE")
    assert result.tokens_used == 100


def test_dispatch_via_swarm_still_uses_subprocess_for_kimi(tmp_path: Path) -> None:
    """Regression sentinel: swarm/kimi still routes through xaxiu-swarm
    subprocess.  Only the explicit direct-HTTP backend list (currently
    {'mimo'}) gets bypassed."""
    import importlib
    worker_mod = importlib.import_module("harness.coord.worker")
    importlib.reload(worker_mod)
    real_dispatch = worker_mod._dispatch_via_swarm

    packet = tmp_path / "packet.md"
    packet.write_text("hi", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()

    fake_proc = MagicMock(returncode=0, stdout="done", stderr="")
    with patch.object(worker_mod.subprocess, "run",
                      return_value=fake_proc) as mock_subproc:
        with patch("harness.engines.dispatcher.dispatch_packet") as mock_dispatch:
            real_dispatch(packet, "swarm/kimi", wt)
            mock_subproc.assert_called_once()
            mock_dispatch.assert_not_called()
            # Confirm xaxiu-swarm was the binary invoked
            args = mock_subproc.call_args.args[0]
            assert args[0] == "xaxiu-swarm"
            assert "--backend" in args and "kimi" in args


def test_run_worker_handles_worktree_missing_dispatch_failure(tmp_path: Path) -> None:
    """When dispatch raises WorktreeMissing, worker fails cleanly with error_tag set."""
    from harness.errors import WorktreeMissing

    run_dir = tmp_path / "runs" / "20260520T220000-ab12"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()
    src_file = tmp_path / "src" / "foo.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("old\n", encoding="utf-8")

    def _raise(*_a, **_k):
        raise WorktreeMissing("worktree not found: ghost",
                              context={"engine": "swarm/kimi"})

    with patch("harness.coord.worker._dispatch_via_swarm", side_effect=_raise):
        result = run_worker(task, run_dir, project_root=tmp_path)

    assert result["state"] == "failed"
    assert result["error_tag"] == "L4.dispatch.E_MISSING_WORKTREE"
    assert "worktree not found" in result["diagnostic"]

    # Checkpoint must mark state=failed (not in_progress orphan)
    ckpt = read_checkpoint(run_dir / "checkpoints" / "worker-1.json")
    assert ckpt is not None
    assert ckpt.state == "failed"

    # Side-channel error file must exist
    err_path = run_dir / "checkpoints" / "worker-1.error.json"
    assert err_path.exists()
    err = json.loads(err_path.read_text(encoding="utf-8"))
    assert err["error_tag"] == "L4.dispatch.E_MISSING_WORKTREE"


# ---------------------------------------------------------------------------
# W5-BB strict-path packet injection
# ---------------------------------------------------------------------------

def test_build_prompt_omits_strict_paths_section_when_empty() -> None:
    """No strict_paths → no STRICT PATHS callout in the packet."""
    task = SimpleNamespace(worker_id="worker-1")
    step = SimpleNamespace(
        step_id="s1", kind="edit",
        instruction="Do a thing.",
        target_files=["src/foo.py"],
    )
    prompt = _build_prompt(task, step, read_set_contents={}, strict_paths=[])
    assert "STRICT PATHS" not in prompt


def test_build_prompt_injects_strict_paths_section_when_overlap() -> None:
    """W5-BB: when a step's target_files intersect strict_paths, the
    packet must contain the STRICT PATHS callout listing those paths."""
    task = SimpleNamespace(worker_id="worker-1")
    step = SimpleNamespace(
        step_id="s1", kind="create",
        instruction="Create the report.",
        target_files=["coord/operator/report.md"],
    )
    prompt = _build_prompt(
        task, step, read_set_contents={},
        strict_paths=["coord/operator/report.md", "coord/other.md"],
    )
    assert "STRICT PATHS" in prompt
    assert "coord/operator/report.md" in prompt
    # The non-overlapping strict path must NOT appear (this step doesn't
    # own it; another worker will).
    assert "coord/other.md" not in prompt.split("STRICT PATHS")[1].split(
        "Context Files"
    )[0]


def test_build_prompt_no_section_when_no_overlap() -> None:
    """W5-BB: strict_paths declared but none in this step's target_files
    → don't inject the callout (would be misleading)."""
    task = SimpleNamespace(worker_id="worker-1")
    step = SimpleNamespace(
        step_id="s1", kind="edit",
        instruction="Touch foo.",
        target_files=["src/foo.py"],
    )
    prompt = _build_prompt(
        task, step, read_set_contents={},
        strict_paths=["coord/totally/other.md"],
    )
    assert "STRICT PATHS" not in prompt


# ---------------------------------------------------------------------------
# W6-A1.2 fallback progress events
# ---------------------------------------------------------------------------

def test_fallback_emits_progress_events_when_primary_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6-A1.2: when primary returns 0 edits and a fallback engine is
    configured, the worker must emit `fallback_attempted`,
    `fallback_dispatch_result`, and `fallback_edits_applied` progress
    events.  This closes the observability gap surfaced in W6-A1's
    silent-fallback investigation."""
    run_dir = tmp_path / "runs" / "20260523T000000-test"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    # Override the autouse stub: primary returns success=True but EMPTY
    # text (simulates engine drift — protocol broken, 0 edits parseable).
    empty_primary = SimpleNamespace(
        success=True, text="", error=None, tokens_used=0, cost_usd=0.0,
    )
    # Fallback returns a valid FILE/REPLACE that creates src/foo.py.
    fb_response = SimpleNamespace(
        success=True,
        text=(
            "FILE: src/foo.py\n"
            "<<<<<<< SEARCH\n"
            "=======\n"
            "# fallback rescue\n"
            ">>>>>>> REPLACE\n"
        ),
        error=None, tokens_used=0, cost_usd=0.0,
    )

    call_count = {"n": 0}

    def _alternating(*args, **kwargs):
        call_count["n"] += 1
        return empty_primary if call_count["n"] == 1 else fb_response

    with patch("harness.coord.worker._dispatch_via_swarm",
               side_effect=_alternating), \
         patch("harness.coord.worker._run_pytest",
               return_value={"ran": 0, "passed": 0, "failed": 0,
                             "skipped": 0, "duration_seconds": 0.0}), \
         patch("harness.coord.worker.worktree_path",
               return_value=tmp_path), \
         patch("harness.coord.worker.write_checkpoint"):
        run_worker(
            task, run_dir,
            engine="swarm/mimo",
            fallback_engine="swarm/deepseek",
            project_root=tmp_path,
        )

    # Inspect the progress jsonl for the new events
    progress_path = run_dir / "checkpoints" / "worker-1.progress.jsonl"
    assert progress_path.exists(), "progress log missing"
    events = [
        json.loads(line) for line in
        progress_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    event_names = [e.get("event") for e in events]
    assert "fallback_attempted" in event_names, f"missing fallback_attempted: {event_names}"
    assert "fallback_dispatch_result" in event_names, f"missing fallback_dispatch_result: {event_names}"
    assert "fallback_edits_applied" in event_names, f"missing fallback_edits_applied: {event_names}"
    # The attempted event should name both engines
    attempted = next(e for e in events if e["event"] == "fallback_attempted")
    assert attempted["primary_engine"] == "swarm/mimo"
    assert attempted["fallback_engine"] == "swarm/deepseek"


def test_existing_write_set_files_preloaded_into_prompt_context(
    tmp_path: Path,
) -> None:
    """W6-A1-3: planners frequently emit read_set=[] for tasks that edit
    existing files (they treat 'write' as implying 'no read needed').  The
    worker must pre-load existing write_set files into the prompt context
    so the engine can produce FILE/REPLACE blocks with matching anchors.
    Without this, engines either silent_no_op (no anchors to match) or
    skip the file (W6-A1 run4: kimi-api edited only tests/test_doctor.py
    because src/harness/doctor.py wasn't in context)."""
    run_dir = tmp_path / "runs" / "20260523T000000-w6a13"
    run_dir.mkdir(parents=True)

    # Existing file on disk in the repo root with distinctive content
    src_file = tmp_path / "src" / "existing.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text(
        "SENTINEL_EXISTING_FUNCTION_BODY\ndef existing():\n    return 42\n",
        encoding="utf-8",
    )

    # Task with read_set=[] but write_set names the existing file.
    task = {
        "worker_id": "worker-1",
        "title": "Edit existing file",
        "description": "Add a helper",
        "read_set": [],
        "write_set": ["src/existing.py"],
        "test_set": [],
        "depends_on": [],
        "steps": [
            {
                "step_id": "s1",
                "kind": "edit",
                "instruction": "Add a helper function",
                "target_files": ["src/existing.py"],
                "expected_diff_lines": 5,
                "required_tests": [],
            },
        ],
        "estimated_kimi_minutes": 1,
        "max_context_tokens": 30000,
    }

    captured: dict = {}

    def _capture_packet(packet_path: Path, engine, wt_path):
        captured["prompt"] = Path(packet_path).read_text(encoding="utf-8")
        return SimpleNamespace(
            success=True,
            text=(
                "FILE: src/existing.py\n"
                "<<<<<<< SEARCH\n"
                "=======\n"
                "# helper appended\n"
                ">>>>>>> REPLACE\n"
            ),
            error=None, tokens_used=0, cost_usd=0.0,
        )

    with patch("harness.coord.worker._dispatch_via_swarm",
               side_effect=_capture_packet), \
         patch("harness.coord.worker._run_pytest",
               return_value={"ran": 0, "passed": 0, "failed": 0,
                             "skipped": 0, "duration_seconds": 0.0}):
        run_worker(task, run_dir, project_root=tmp_path)

    prompt = captured.get("prompt", "")
    assert "SENTINEL_EXISTING_FUNCTION_BODY" in prompt, (
        "write_set file's existing content was not embedded in the worker "
        "prompt; engine has no anchors for FILE/REPLACE edits.  Snippet: "
        f"{prompt[:500]}"
    )


def test_nonexistent_write_set_files_skipped_in_prompt_context(
    tmp_path: Path,
) -> None:
    """W6-A1-3: write_set files that don't exist on disk yet (the
    create-new-file case) must NOT cause an error during prompt assembly.
    The engine uses the empty-SEARCH create idiom for new files."""
    run_dir = tmp_path / "runs" / "20260523T000000-w6a13"
    run_dir.mkdir(parents=True)

    task = {
        "worker_id": "worker-1",
        "title": "Create a new module",
        "description": "Brand-new file",
        "read_set": [],
        "write_set": ["src/brand_new.py"],
        "test_set": [],
        "depends_on": [],
        "steps": [
            {
                "step_id": "s1",
                "kind": "create",
                "instruction": "Create the module",
                "target_files": ["src/brand_new.py"],
                "expected_diff_lines": 5,
                "required_tests": [],
            },
        ],
        "estimated_kimi_minutes": 1,
        "max_context_tokens": 30000,
    }

    create_response = SimpleNamespace(
        success=True,
        text=(
            "FILE: src/brand_new.py\n"
            "<<<<<<< SEARCH\n"
            "=======\n"
            "# brand new\n"
            ">>>>>>> REPLACE\n"
        ),
        error=None, tokens_used=0, cost_usd=0.0,
    )

    with patch("harness.coord.worker._dispatch_via_swarm",
               return_value=create_response), \
         patch("harness.coord.worker._run_pytest",
               return_value={"ran": 0, "passed": 0, "failed": 0,
                             "skipped": 0, "duration_seconds": 0.0}):
        # Must not raise; create-flow proceeds with no existing content.
        result = run_worker(task, run_dir, project_root=tmp_path)

    assert "src/brand_new.py" in result["files_modified"]


def test_fallback_emits_exception_event_when_fallback_crashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6-A1.2: if the fallback dispatch itself raises, the worker emits
    a `fallback_exception` event so the failure is visible (not silently
    swallowed by the broad except block)."""
    run_dir = tmp_path / "runs" / "20260523T000000-test"
    run_dir.mkdir(parents=True)
    task = _valid_task_dict()

    empty_primary = SimpleNamespace(
        success=True, text="", error=None, tokens_used=0, cost_usd=0.0,
    )

    call_count = {"n": 0}

    def _crash_on_fallback(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return empty_primary
        raise RuntimeError("simulated fallback dispatch crash")

    with patch("harness.coord.worker._dispatch_via_swarm",
               side_effect=_crash_on_fallback), \
         patch("harness.coord.worker._run_pytest",
               return_value={"ran": 0, "passed": 0, "failed": 0,
                             "skipped": 0, "duration_seconds": 0.0}), \
         patch("harness.coord.worker.worktree_path",
               return_value=tmp_path), \
         patch("harness.coord.worker.write_checkpoint"):
        run_worker(
            task, run_dir,
            engine="swarm/mimo",
            fallback_engine="swarm/deepseek",
            project_root=tmp_path,
        )

    progress_path = run_dir / "checkpoints" / "worker-1.progress.jsonl"
    events = [
        json.loads(line) for line in
        progress_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    event_names = [e.get("event") for e in events]
    assert "fallback_exception" in event_names, f"missing fallback_exception: {event_names}"
    exc_event = next(e for e in events if e["event"] == "fallback_exception")
    assert "RuntimeError" in exc_event["exception"]
    assert "simulated fallback dispatch crash" in exc_event["exception"]
