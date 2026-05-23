"""W6-A1.1 evidence script: verify D5 worktree-branching against a real run.

Usage:
    python scripts/verify_d5_worktree_branching.py <run-id>

Default: 20260523T142354-79ed (the W6-A1 run-1 that triggered the
investigation).

For the given run, checks:
1. Each non-root worker's branch contains its declared depends_on
   parent's commit in git history.
2. The presence of the parent commit proves the worktree was
   branched FROM the parent — not from master.

Exit codes:
    0  all multi-worker deps verified
    1  at least one dependent worker did NOT inherit parent commits
    2  run directory missing / plan unreadable
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str], cwd: Path | None = None) -> str:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, check=False, cwd=cwd,
        ).stdout
    except OSError:
        return ""


def main(run_id: str = "20260523T142354-79ed") -> int:
    repo = Path.cwd()
    run_dir = repo / "runs" / run_id
    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        print(f"ERROR: plan.json missing at {plan_path}", file=sys.stderr)
        return 2

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    tasks = plan.get("tasks", [])
    if not tasks:
        print(f"ERROR: no tasks in plan", file=sys.stderr)
        return 2

    # Map worker_id → commit_sha from checkpoints
    ckpt_dir = run_dir / "checkpoints"
    worker_shas: dict[str, str] = {}
    for task in tasks:
        wid = task["worker_id"]
        ck_path = ckpt_dir / f"{wid}.json"
        if not ck_path.exists():
            continue
        ck = json.loads(ck_path.read_text(encoding="utf-8"))
        sha = ck.get("commit_sha")
        if sha:
            worker_shas[wid] = sha

    print(f"=== D5 worktree-branching verification for run {run_id} ===")
    print(f"Workers with commits: {worker_shas}")
    print()

    failures = 0
    for task in tasks:
        wid = task["worker_id"]
        deps = task.get("depends_on") or []
        if not deps:
            print(f"  {wid}: no deps (root worker) — n/a")
            continue
        wt_branch = f"wt/{run_id}/{wid}"
        # Get the branch's commit log
        log_output = _run(["git", "log", "--oneline", wt_branch], cwd=repo)
        if not log_output:
            print(f"  {wid}: WARN — could not read branch {wt_branch}")
            failures += 1
            continue
        commits_in_branch = [
            line.split()[0] for line in log_output.splitlines() if line
        ]
        for dep_id in deps:
            dep_sha = worker_shas.get(dep_id)
            if not dep_sha:
                print(f"  {wid}: WARN — dep {dep_id} has no commit; can't verify")
                continue
            dep_sha_short = dep_sha[:7]
            if any(c.startswith(dep_sha_short) for c in commits_in_branch):
                print(f"  {wid}: OK — branch contains {dep_id}'s commit "
                      f"{dep_sha_short} (D5 working)")
            else:
                print(f"  {wid}: FAIL — branch does NOT contain {dep_id}'s "
                      f"commit {dep_sha_short} (D5 broken)")
                failures += 1
    print()
    if failures == 0:
        print(f"VERDICT: D5 verified working on run {run_id}")
        return 0
    print(f"VERDICT: D5 broken — {failures} dependency violations")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
