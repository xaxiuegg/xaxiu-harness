"""V2-FIRST-RUN smoke test: planner + worker via MockEngine, end-to-end.

This is the first integration test that exercises the full v2/B + v2/C
pipeline against a real (temporary) git repo, with no network calls.
It proves:

1. ``planner.plan()`` produces a valid ``WavePlan`` when dispatched to
   ``MockEngine`` (force_engine="mock").
2. ``worker.run_worker()`` builds a FILE/REPLACE prompt, dispatches it
   to ``MockEngine``, parses the response, applies edits inside the
   worker's git worktree, and writes a ``completed`` checkpoint.
3. The worktree-isolation contract holds: the worker's edits land inside
   ``.harness/worktrees/<run_id>/<worker_id>/`` and not in the repo root.

If this test passes, the v2 architecture works.

The Coordinator's subprocess-based worker spawning is exercised separately
(test_coord_coordinator.py).  This test deliberately calls run_worker
in-process so the smoke is fast and free of subprocess flake.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.coord.planner import plan, write_plan
from harness.coord.worker import run_worker
from harness.coord.worktree import create_worktree, worktree_path, WORKTREE_ROOT


SAMPLE_SPEC = Path(__file__).resolve().parents[1] / "spec" / "samples" / "hello-world.md"


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Initialize a tiny git repo with one commit on ``master`` as the base branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "master"], repo)
    _git(["config", "user.email", "smoke@test.local"], repo)
    _git(["config", "user.name", "Smoke Test"], repo)
    # Seed file so master has a commit
    (repo / "README.md").write_text("# smoke repo\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-m", "init"], repo)
    # Copy sample spec into the repo so the planner's repo_tree includes it
    spec_dir = repo / "spec" / "samples"
    spec_dir.mkdir(parents=True)
    shutil.copy(SAMPLE_SPEC, spec_dir / "hello-world.md")
    return repo


def test_planner_emits_valid_waveplan_via_mock(tmp_repo: Path) -> None:
    """Planner → MockEngine → valid WavePlan JSON."""
    spec_path = tmp_repo / "spec" / "samples" / "hello-world.md"
    waveplan = plan(spec_path, engine="mock", project_root=tmp_repo)
    assert waveplan.planner_engine == "mock"
    assert len(waveplan.tasks) == 1
    task = waveplan.tasks[0]
    assert task.worker_id == "worker-1"
    assert len(task.steps) == 1
    assert task.steps[0].kind == "edit"
    assert task.steps[0].target_files == ["mock-out-1.txt"]


def test_worker_applies_mock_edits_inside_worktree(tmp_repo: Path) -> None:
    """worker.run_worker → MockEngine → file lands inside the worktree."""
    spec_path = tmp_repo / "spec" / "samples" / "hello-world.md"
    waveplan = plan(spec_path, engine="mock", project_root=tmp_repo)
    run_id = waveplan.run_id
    run_dir = tmp_repo / "runs" / run_id
    write_plan(waveplan, run_dir)

    # Create the worktree the Coordinator would normally create
    create_worktree(run_id, "worker-1", base_branch="master", repo_root=tmp_repo)

    task = waveplan.tasks[0]
    result = run_worker(
        task.model_dump(),
        run_dir,
        engine="mock",
        project_root=tmp_repo,
    )
    assert result["state"] == "completed", result
    assert "mock-out-1.txt" in result["files_modified"]

    # Verify the file landed inside the worker's worktree
    wt = worktree_path(run_id, "worker-1", tmp_repo / WORKTREE_ROOT)
    out = wt / "mock-out-1.txt"
    assert out.exists(), f"expected {out} to exist"
    assert out.read_text(encoding="utf-8").strip() == "hello from MockEngine"

    # And NOT in the repo root (worktree isolation)
    assert not (tmp_repo / "mock-out-1.txt").exists(), \
        "worker leaked file into repo root"

    # Checkpoint state
    ckpt_path = run_dir / "checkpoints" / "worker-1.json"
    assert ckpt_path.exists()
    ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert ckpt["state"] == "completed"
    assert ckpt["tests_passed"] is True
    assert ckpt["commit_sha"] is not None


# -- W5-E E2E success-path: full plan → worker → integrate cycle --------


def test_full_coord_pipeline_succeeds_via_mock_engine(tmp_repo: Path) -> None:
    """W5-E success-path E2E proof.  Complements W4-L (failure-path proof).

    Walks the full coord pipeline (planner → worker → integrator) via
    MockEngine and asserts:
      - Plan generation produces a valid WavePlan
      - Worker applies the mock edits inside its worktree
      - Integrator merges the worker branch back to master without conflict
      - IntegrationReport.success is True
      - The merged file lands in the repo root (proving the worktree merge
        cycle moved the file out of the worker isolation)

    This proves the W4-A/B silent-failure guards do NOT false-fire on a
    legitimately-successful run — the inverse of W4-L.
    """
    from harness.coord.integrator import integrate
    from harness.coord.run_state import write_run_state
    from harness.coord.schemas import RunState

    spec_path = tmp_repo / "spec" / "samples" / "hello-world.md"
    waveplan = plan(spec_path, engine="mock", project_root=tmp_repo)
    run_id = waveplan.run_id
    run_dir = tmp_repo / "runs" / run_id
    write_plan(waveplan, run_dir)
    create_worktree(run_id, "worker-1", base_branch="master", repo_root=tmp_repo)

    # Run worker → produces a checkpoint + commit on the worker branch
    task = waveplan.tasks[0]
    result = run_worker(
        task.model_dump(),
        run_dir,
        engine="mock",
        project_root=tmp_repo,
    )
    assert result["state"] == "completed"
    assert result["commit_sha"] is not None

    # Persist a run_state so integrator sees the run finished
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    run_state = RunState(
        run_id=run_id,
        spec_path=str(spec_path),
        state="integrating",
        plan_path=str(run_dir / "plan.json"),
        started_at=now_iso,
        last_tick_at=now_iso,
    )
    write_run_state(run_dir / "run_state.json", run_state)

    # Integrate: merge the worker branch into master
    report = integrate(
        run_dir,
        project_root=tmp_repo,
        merge_workers=True,
        pytest_timeout=10,  # short — mock-out file alone, no test run needed
    )

    # The integrator must report success and have moved the file
    # out of the worker's isolated worktree into the repo root.
    assert "worker-1" in report.workers_merged, (
        f"worker-1 should have merged successfully; got "
        f"merged={report.workers_merged} conflicted={report.workers_conflicted} "
        f"diagnostic={report.diagnostic}"
    )
    # File now visible in repo root (the merge moved it out of the worktree)
    assert (tmp_repo / "mock-out-1.txt").exists(), (
        "merged file should be in repo root after integrator merge"
    )
    # And the file content matches the worker's output
    assert (tmp_repo / "mock-out-1.txt").read_text(
        encoding="utf-8"
    ).strip() == "hello from MockEngine"
