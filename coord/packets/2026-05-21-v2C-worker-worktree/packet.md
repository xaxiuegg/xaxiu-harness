# Packet: v2/C — Worker + worktree management + checkpoint writer

## Mission

Per `spec/multi-agent-harness-architecture.md` §3.3 + §6: implement the Worker module that executes one `WorkerTask` inside an isolated git worktree, writes a `WorkerResult`, and emits step-level checkpoints for resume.

**Depends on v2/B** (imports `harness.coord.schemas`). If v2/B has not yet landed when this packet runs, mock the schemas in tests (the source module references the symbols at runtime, not import-time, so deferred imports work).

## In-scope NEW files

- `src/harness/coord/worktree.py` — `create_worktree(run_id, worker_id) -> Path`, `remove_worktree`, `worker_branch_name`
- `src/harness/coord/checkpoint.py` — `Checkpoint` Pydantic model + `read_checkpoint(path)` / `write_checkpoint(path, checkpoint)` (atomic)
- `src/harness/coord/worker.py` — `run_worker(task, run_dir, engine, resume_from=None) -> WorkerResult`
- `tests/test_coord_worktree.py`
- `tests/test_coord_checkpoint.py`
- `tests/test_coord_worker.py`

## In-scope MODIFY files

NONE.  CLI wiring lands in v2/D.

## worktree.py

```python
from __future__ import annotations
import subprocess
from pathlib import Path

WORKTREE_ROOT = Path(".harness") / "worktrees"


def worker_branch_name(run_id: str, worker_id: str) -> str:
    return f"wt/{run_id}/{worker_id}"


def worktree_path(run_id: str, worker_id: str,
                  root: Path = WORKTREE_ROOT) -> Path:
    return root / run_id / worker_id


def create_worktree(
    run_id: str,
    worker_id: str,
    *,
    base_branch: str = "master",
    repo_root: Path | None = None,
) -> Path:
    """git worktree add <path> -b <branch> <base>"""
    repo = repo_root or Path.cwd()
    path = worktree_path(run_id, worker_id, repo / WORKTREE_ROOT)
    branch = worker_branch_name(run_id, worker_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path  # idempotent — already created
    subprocess.run(
        ["git", "worktree", "add", str(path), "-b", branch, base_branch],
        check=True, cwd=repo, capture_output=True,
    )
    return path


def remove_worktree(
    run_id: str, worker_id: str,
    *, repo_root: Path | None = None, force: bool = False,
) -> bool:
    """git worktree remove <path> [--force]"""
    repo = repo_root or Path.cwd()
    path = worktree_path(run_id, worker_id, repo / WORKTREE_ROOT)
    if not path.exists():
        return False
    args = ["git", "worktree", "remove", str(path)]
    if force:
        args.append("--force")
    subprocess.run(args, check=False, cwd=repo, capture_output=True)
    return not path.exists()


def list_worktrees(repo_root: Path | None = None) -> list[Path]:
    """Return paths of all `wt/...` worktrees."""
    repo = repo_root or Path.cwd()
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            p = Path(line.split(" ", 1)[1])
            if "/.harness/worktrees/" in str(p).replace("\\", "/"):
                paths.append(p)
    return paths
```

## checkpoint.py

```python
from __future__ import annotations
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    worker_id: str = Field(pattern=r"^worker-\d+$")
    run_id: str
    last_completed_step_id: str | None = None
    last_completed_step_index: int = Field(ge=-1, default=-1)
    files_modified: list[str] = Field(default_factory=list, max_length=50)
    tests_passed: bool = False
    tests_summary: str = ""
    elapsed_seconds: int = Field(ge=0, default=0)
    state: Literal["pending", "in_progress", "completed", "failed"] = "in_progress"
    updated_at: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_checkpoint(path: Path) -> Checkpoint | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return Checkpoint.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_checkpoint(path: Path, checkpoint: Checkpoint) -> None:
    """Atomic write via tempfile + os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not checkpoint.updated_at:
        checkpoint = checkpoint.model_copy(update={"updated_at": now_iso()})
    fd, tmp_name = tempfile.mkstemp(dir=p.parent, prefix=".ckpt_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(checkpoint.model_dump_json(indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, p)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
```

## worker.py

```python
from __future__ import annotations
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from harness.coord.checkpoint import (
    Checkpoint, read_checkpoint, write_checkpoint, now_iso,
)


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
    # Best-effort parse "N passed, M failed in X.YYs"
    import re
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
    from harness.coord.worktree import worktree_path
    from harness.coord.schemas import (
        WorkerTask, WorkerResult, WorkerStateLiteral, TestSummary,
    )

    task_obj = WorkerTask.model_validate(task) if isinstance(task, dict) else task
    repo = project_root or Path.cwd()
    wt_path = worktree_path(task_obj.worker_id_run_id_pair(), task_obj.worker_id) if hasattr(
        task_obj, "worker_id_run_id_pair"
    ) else (repo / ".harness" / "worktrees" / run_dir.name / task_obj.worker_id)

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

    result = {
        "schema_version": 1,
        "worker_id": task_obj.worker_id,
        "run_id": run_dir.name,
        "state": final_state,
        "started_at": started_at,
        "finished_at": now_iso(),
        "steps_completed": [s.step_id for s in task_obj.steps[:idx+1]] if task_obj.steps else [],
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
```

(Note: `task_obj.worker_id_run_id_pair()` is a placeholder — if schemas don't expose this, use a simple helper. v2/D will refine.)

## Tests required

worktree (test_coord_worktree.py): 5+
- create_worktree creates path + branch (mock git subprocess)
- create_worktree is idempotent (second call no-ops)
- remove_worktree returns False when missing
- worker_branch_name follows wt/<run>/<worker> pattern
- list_worktrees parses --porcelain output

checkpoint (test_coord_checkpoint.py): 6+
- Checkpoint rejects bad worker_id pattern
- write_checkpoint creates file + parent dir
- read_checkpoint on missing returns None
- read_checkpoint on corrupt returns None
- write_checkpoint atomic-write contract (mock os.replace to fail; original intact)
- updated_at auto-populated if not provided

worker (test_coord_worker.py): 5+
- run_worker on fresh task creates initial checkpoint
- run_worker resumes from existing checkpoint
- run_worker with empty test_set returns 0/0/0 summary
- worker writes deliverable JSON to runs/<id>/deliverables/<wid>.json
- worker state transitions through "in_progress" → "completed"

Target ≥16 new tests.

## Acceptance criteria

1. `from harness.coord import worktree, checkpoint, worker` works.
2. `create_worktree("test_run", "worker-1", base_branch="master")` creates `.harness/worktrees/test_run/worker-1/` and a branch named `wt/test_run/worker-1` (mock-tested).
3. Checkpoint roundtrips via Pydantic.
4. `python -m pytest tests/ -q` shows green.
5. Single commit: `feat(coord): worker + worktree + checkpoint (v2/C)`.

## Reference

- `spec/multi-agent-harness-architecture.md` §3.3 and §6
- `src/harness/coord/schemas.py` (v2/B sibling) — Pydantic models worker imports
- `git worktree` docs — pattern for isolation
- `src/harness/status/store.py` — atomic-write reference

## Output format

6 new files + 0 modifications + 1 commit. Subprocess calls to `git worktree` and `pytest` are mocked in tests; no actual worktree creation needed for CI.
