"""Integrator: merge worker branches, run tests, optionally commit + push."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from harness.coord.checkpoint import read_checkpoint
from harness.coord.run_state import read_run_state, write_run_state
from harness.coord.schemas import IntegratorStatus, RunState, RunStateLiteral, WavePlan
from harness.coord.worktree import worker_branch_name


@dataclass
class IntegrationReport:
    success: bool
    commit_sha: str | None = None
    pushed: bool = False
    test_summary: dict[str, int] | None = None
    diagnostic: str = ""
    workers_merged: list[str] = field(default_factory=list)
    workers_skipped: list[str] = field(default_factory=list)
    workers_conflicted: list[str] = field(default_factory=list)


def _git(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a git subcommand and return (rc, stdout, stderr)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _merge_worker_branches(
    plan: WavePlan,
    run_dir: Path,
    project_root: Path,
) -> tuple[list[str], list[str], list[str], str]:
    """Merge each completed worker's branch back into the current branch.

    Honours ``plan.integration_strategy``:

    - ``squash`` — ``git merge --squash <branch>`` then stage (no commit; the
      operator/auto-commit path makes a single integration commit).
    - ``merge``  — fast-forward / true merge with a generated commit message.
    - ``rebase`` — currently aliased to ``merge`` (rebasing per-worker into
      the base branch would re-order history in non-obvious ways; revisit
      when an operator requests it).

    Returns ``(merged, skipped, conflicted, diagnostic)``.
    """
    merged: list[str] = []
    skipped: list[str] = []
    conflicted: list[str] = []
    checkpoints_dir = run_dir / "checkpoints"

    for task in plan.tasks:
        ckpt = read_checkpoint(checkpoints_dir / f"{task.worker_id}.json")
        if ckpt is None or ckpt.state != "completed" or not ckpt.commit_sha:
            skipped.append(task.worker_id)
            continue

        branch = worker_branch_name(plan.run_id, task.worker_id)
        # Verify branch exists
        rc, _, _ = _git("rev-parse", "--verify", branch, cwd=project_root)
        if rc != 0:
            skipped.append(task.worker_id)
            continue

        if plan.integration_strategy == "squash":
            rc, _, err = _git("merge", "--squash", "--no-commit", branch, cwd=project_root)
        else:
            rc, _, err = _git(
                "merge", "--no-ff", "--no-edit",
                "-m", f"integrate({plan.run_id}): {task.worker_id} — {task.title}",
                branch, cwd=project_root,
            )

        if rc != 0:
            conflicted.append(task.worker_id)
            _git("merge", "--abort", cwd=project_root)
            return merged, skipped, conflicted, f"merge conflict on {task.worker_id}: {err.strip()[:200]}"
        merged.append(task.worker_id)

    return merged, skipped, conflicted, ""


def integrate(
    run_dir: Path,
    *,
    project_root: Path | None = None,
    auto_commit: bool = False,
    auto_push: bool = False,
    merge_workers: bool = True,
) -> IntegrationReport:
    """Integrate a completed run: merge worker branches, run tests, optionally commit + push.

    When ``merge_workers=True`` (default) and a ``plan.json`` lives in
    ``run_dir``, each completed worker's branch is merged into the current
    branch per ``plan.integration_strategy`` before tests run.  The merge
    step is best-effort: on conflict the merge is aborted and the integrator
    reports ``workers_conflicted`` so the operator (or a replan loop) can
    decide what to do.
    """
    run_dir = Path(run_dir)
    state = read_run_state(run_dir / "run_state.json")
    if state is None:
        return IntegrationReport(success=False, diagnostic="No run_state found")

    pr = project_root or Path.cwd()

    # Merge worker branches (best-effort)
    merged: list[str] = []
    skipped: list[str] = []
    conflicted: list[str] = []
    merge_diag = ""
    plan_path = run_dir / "plan.json"
    if merge_workers and plan_path.exists():
        try:
            plan = WavePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
            merged, skipped, conflicted, merge_diag = _merge_worker_branches(
                plan, run_dir, pr,
            )
        except Exception as exc:
            merge_diag = f"merge step failed: {exc}"

    if conflicted:
        return IntegrationReport(
            success=False,
            workers_merged=merged,
            workers_skipped=skipped,
            workers_conflicted=conflicted,
            diagnostic=merge_diag,
        )

    # Run pytest and collect summary
    test_summary: dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "-q", "--tb=no"],
            cwd=pr,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        # Parse summary line like "2 passed, 1 failed, 3 skipped in 0.01s"
        for line in proc.stdout.splitlines():
            if "passed" in line or "failed" in line or "error" in line or "skipped" in line:
                parts = line.replace(" in ", " ").replace(",", "").split()
                for i, word in enumerate(parts):
                    if word == "passed":
                        try:
                            test_summary["passed"] = int(parts[i - 1])
                        except (IndexError, ValueError):
                            pass
                    elif word == "failed":
                        try:
                            test_summary["failed"] = int(parts[i - 1])
                        except (IndexError, ValueError):
                            pass
                    elif word.startswith("error"):
                        try:
                            test_summary["errors"] = int(parts[i - 1])
                        except (IndexError, ValueError):
                            pass
                    elif word == "skipped":
                        try:
                            test_summary["skipped"] = int(parts[i - 1])
                        except (IndexError, ValueError):
                            pass
                break
    except Exception as exc:
        return IntegrationReport(success=False, diagnostic=f"pytest failed: {exc}")

    # Env gate check
    allow_env = os.environ.get("HARNESS_ALLOW_AUTO_INTEGRATE", "").lower()
    if auto_commit and allow_env == "true":
        rc, out, err = _git("add", "-A", cwd=pr)
        if rc != 0:
            return IntegrationReport(success=False, diagnostic=f"git add failed: {err}")
        rc, out, err = _git(
            "commit",
            "-m",
            f"feat(coord): integrate run {state.run_id}",
            cwd=pr,
        )
        if rc != 0 and "nothing to commit" not in (out + err).lower():
            return IntegrationReport(success=False, diagnostic=f"git commit failed: {err}")
        sha = out.strip().splitlines()[-1] if out else None
        pushed = False
        if auto_push and sha:
            rc_push, _, err_push = _git("push", cwd=pr)
            pushed = rc_push == 0
            if rc_push != 0:
                return IntegrationReport(
                    success=False,
                    commit_sha=sha,
                    pushed=False,
                    test_summary=test_summary,
                    diagnostic=f"git push failed: {err_push}",
                )
        state.state = RunStateLiteral.COMPLETED
        state.integrator_status = IntegratorStatus(
            state="done",
            last_action="commit+push" if pushed else "commit",
            commit_sha=sha,
        )
        write_run_state(run_dir / "run_state.json", state)
        return IntegrationReport(
            success=True,
            commit_sha=sha,
            pushed=pushed,
            test_summary=test_summary,
            workers_merged=merged,
            workers_skipped=skipped,
            workers_conflicted=conflicted,
        )

    # No auto-commit or gate not set
    state.state = RunStateLiteral.COMPLETED
    state.integrator_status = IntegratorStatus(
        state="done",
        last_action="dry_run",
    )
    write_run_state(run_dir / "run_state.json", state)
    return IntegrationReport(
        success=test_summary.get("failed", 0) == 0 and test_summary.get("errors", 0) == 0,
        test_summary=test_summary,
        diagnostic="" if test_summary.get("failed", 0) == 0 else "Tests failed",
        workers_merged=merged,
        workers_skipped=skipped,
        workers_conflicted=conflicted,
    )
