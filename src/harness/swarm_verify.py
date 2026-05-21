"""Verify Kimi-CLI landings against expected file paths (SWARM-LANDING-VERIFY).

Closes the "timeout-but-actually-landed" gap documented in
``feedback_kimi_cli_incremental_edits``.  Reads the most recent
``.swarm/runs/<id>/swarm.json`` (or one specified via --run-id), pairs
each completed worker against its declared deliverable + the actual
git diff, and reports which expected paths the worker mutated.

Output is a list of LandingResult per expected path:

  expected_path, status (mutated | unmutated | not_in_diff), worker_id,
  swarm_status (completed | timeout | failed | running)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_DEFAULT_SWARM_ROOT = Path(".swarm") / "runs"


@dataclass(frozen=True)
class LandingResult:
    expected_path: str
    status: str          # "mutated" | "unmutated" | "not_in_diff"
    worker_id: str | None = None
    swarm_status: str | None = None


def _latest_swarm_run(swarm_root: Path = _DEFAULT_SWARM_ROOT) -> Path | None:
    if not swarm_root.exists():
        return None
    runs = sorted(p for p in swarm_root.iterdir() if p.is_dir())
    return runs[-1] if runs else None


def _read_swarm_state(run_dir: Path) -> dict | None:
    sj = run_dir / "swarm.json"
    if not sj.exists():
        return None
    try:
        return json.loads(sj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _git_diff_files(scope: str = "HEAD") -> set[str]:
    """Return paths changed in *scope*.  Empty set on git failure."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", scope],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return set()
        return {p.strip() for p in proc.stdout.splitlines() if p.strip()}
    except Exception:
        return set()


def _untracked_files() -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return set()
        return {p.strip() for p in proc.stdout.splitlines() if p.strip()}
    except Exception:
        return set()


def verify_landings(
    expected_paths: Iterable[str],
    *,
    run_id: str | None = None,
    swarm_root: Path = _DEFAULT_SWARM_ROOT,
    git_scope: str = "HEAD",
) -> list[LandingResult]:
    """Cross-reference expected paths with git mutations + swarm worker state."""
    expected = list(expected_paths)
    if not expected:
        return []

    # Find the swarm run
    if run_id:
        run_dir = swarm_root / run_id
    else:
        run_dir = _latest_swarm_run(swarm_root)

    workers: list[dict] = []
    if run_dir and run_dir.exists():
        state = _read_swarm_state(run_dir) or {}
        workers = state.get("workers") or []

    modified = _git_diff_files(git_scope) | _untracked_files()

    results: list[LandingResult] = []
    for exp in expected:
        norm = exp.replace("\\", "/")
        status = "mutated" if norm in modified else "unmutated"
        # Best-effort: pair with a worker whose packet path mentions exp
        wid: str | None = None
        wstatus: str | None = None
        for w in workers:
            packet = (w.get("packet") or "").replace("\\", "/")
            if norm in packet:
                wid = w.get("id")
                wstatus = w.get("status")
                break
        if status == "unmutated" and modified and norm not in modified:
            status = "not_in_diff"
        results.append(LandingResult(
            expected_path=exp, status=status, worker_id=wid, swarm_status=wstatus,
        ))
    return results


def summarize(results: list[LandingResult]) -> dict[str, int]:
    summary = {"mutated": 0, "unmutated": 0, "not_in_diff": 0}
    for r in results:
        if r.status in summary:
            summary[r.status] += 1
        else:
            summary["unmutated"] += 1
    return summary
