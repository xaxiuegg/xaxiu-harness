from __future__ import annotations

import subprocess
from pathlib import Path

WORKTREE_ROOT = Path(".harness") / "worktrees"


def worker_branch_name(run_id: str, worker_id: str) -> str:
    return f"wt/{run_id}/{worker_id}"


def worktree_path(run_id: str, worker_id: str, root: Path = WORKTREE_ROOT) -> Path:
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
