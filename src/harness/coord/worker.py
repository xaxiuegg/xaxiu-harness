from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from harness.coord.checkpoint import (
    Checkpoint,
    read_checkpoint,
    write_checkpoint,
    now_iso,
)
from harness.coord.worktree import WORKTREE_ROOT, worktree_path


def _run_pytest(test_set: list[str], cwd: Path, timeout_seconds: int = 300) -> dict:
    """Run pytest on the worker's local test_set; return summary dict."""
    if not test_set:
        return {"ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0}
    start = datetime.now(timezone.utc)
    args = ["python", "-m", "pytest"] + list(test_set) + ["-q", "--tb=line"]
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds,
    )
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    passed = failed = skipped = 0
    m = re.search(r"(\d+) passed", result.stdout)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", result.stdout)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) skipped", result.stdout)
    if m:
        skipped = int(m.group(1))
    return {
        "ran": passed + failed + skipped,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration_seconds": elapsed,
    }


def run_worker(
    task: dict,   # WorkerTask dict (deferred-import friendly)
    run_dir: Path,
    *,
    engine: str = "swarm/kimi",
    resume_from: Path | None = None,
    project_root: Path | None = None,
) -> dict:   # WorkerResult dict
    """Execute one task's steps inside its worktree.

    Idempotent: if a checkpoint exists, resumes from the next step.
    """
    from harness.coord.schemas import (
        WorkerTask, WorkerResult, WorkerStateLiteral, TestSummary,
    )

    task_obj = WorkerTask.model_validate(task) if isinstance(task, dict) else task
    repo = project_root or Path.cwd()
    wt_path = worktree_path(run_dir.name, task_obj.worker_id, repo / WORKTREE_ROOT)

    checkpoint_path = run_dir / "checkpoints" / f"{task_obj.worker_id}.json"
    ckpt = read_checkpoint(checkpoint_path) if resume_from is None else read_checkpoint(resume_from)
    if ckpt is None:
        ckpt = Checkpoint(
            worker_id=task_obj.worker_id,
            run_id=run_dir.name,
            state="in_progress",
        )

    started_at = now_iso()
    files_modified: list[str] = list(ckpt.files_modified or [])

    # Iterate steps starting from last_completed_step_index + 1
    start_idx = ckpt.last_completed_step_index + 1
    idx = start_idx - 1  # default if no steps run
    for idx in range(start_idx, len(task_obj.steps)):
        step = task_obj.steps[idx]
        # NOTE: actual edit application is engine-dispatched.  For v2/C we
        # provide the scaffold; v2/D wires the dispatch.  Tests mock this.
        ckpt = ckpt.model_copy(update={
            "last_completed_step_id": step.step_id,
            "last_completed_step_index": idx,
            "files_modified": list(set(files_modified + step.target_files)),
        })
        write_checkpoint(checkpoint_path, ckpt)
        files_modified = list(ckpt.files_modified)

    # Final test run on the task's test_set (inside worktree)
    tests = _run_pytest(task_obj.test_set, cwd=wt_path)
    final_state = "completed" if tests["failed"] == 0 else "failed"
    ckpt = ckpt.model_copy(update={
        "state": final_state,
        "tests_passed": tests["failed"] == 0,
        "tests_summary": f"{tests['passed']}p/{tests['failed']}f/{tests['skipped']}s",
    })
    write_checkpoint(checkpoint_path, ckpt)

    steps_completed = []
    if task_obj.steps:
        steps_completed = [s.step_id for s in task_obj.steps[:idx + 1]]

    result = {
        "schema_version": 1,
        "worker_id": task_obj.worker_id,
        "run_id": run_dir.name,
        "state": final_state,
        "started_at": started_at,
        "finished_at": now_iso(),
        "steps_completed": steps_completed,
        "files_modified": files_modified,
        "test_summary": tests,
        "commit_sha": None,
        "error_tag": None if final_state == "completed" else "L3.worker.E_TEST_FAILED",
        "diagnostic": "",
        "tokens_used": 0,
        "elapsed_seconds": int((datetime.now(timezone.utc) -
                                datetime.fromisoformat(started_at)).total_seconds()),
    }
    # Write deliverable JSON
    deliv_dir = run_dir / "deliverables"
    deliv_dir.mkdir(parents=True, exist_ok=True)
    (deliv_dir / f"{task_obj.worker_id}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
