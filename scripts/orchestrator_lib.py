"""Shared library for orchestrator architecture demos (Phase 3).

The three architecture demos (A: Claude -p, B: single non-Claude engine,
C: hybrid) all share the same shape:

    1. Read coord/STATUS.csv → pick a TODO row to drive
    2. Compose a spec markdown from the TODO description
    3. (optional) Fire `harness coord run --watch --no-merge`
    4. Report cycle outcome to coord/coverage/orchestrator_<arch>_<stamp>.json

This module holds the engine-agnostic helpers; the per-arch scripts
plug in their specific spec-composer engine.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Make src/ available when running scripts/ standalone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.status.store import read_status  # noqa: E402
from harness.status.schema import Status, StatusRow  # noqa: E402


OPEN_STATES = {
    Status.TODO,
    Status.QUEUED,
    Status.IN_PROGRESS,
    Status.PROPOSED,
    Status.PLANNED,
    Status.PARTIAL,
    Status.SPEC_DONE,
    Status.DESIGN_DONE,
}


@dataclass
class CycleResult:
    arch: str                  # 'A' / 'B' / 'C'
    started_at: str
    elapsed_s: float
    todo_id: str | None        # picked TODO row id
    todo_title: str | None
    spec_path: str | None      # path to composed spec
    spec_lines: int            # # of lines in composed spec
    composer_engine: str       # which engine composed (e.g. 'claude -p', 'mimo', 'deepseek')
    composer_cost_usd: float   # if known
    executed: bool             # whether `harness coord run` actually fired
    execution_outcome: str | None  # 'completed' / 'failed' / 'skipped' / 'error'
    notes: str = ""


def pick_next_todo(status_path: Path | None = None) -> StatusRow | None:
    """Return the first open StatusRow, or None if backlog is empty.

    "Open" = status in {TODO, QUEUED, IN_PROGRESS, ...} per OPEN_STATES.
    """
    path = status_path or Path("coord/STATUS.csv")
    rows = read_status(path)
    for r in rows:
        if r.status in OPEN_STATES:
            return r
    return None


def compose_spec_from_template(todo: StatusRow, spec_dir: Path) -> Path:
    """Compose a *minimal* spec markdown when no engine composer is available.

    Used as the deterministic fallback (Architecture comparison baseline)
    when we want to test the dispatch/run/integrate path independent of
    the spec-composition engine.
    """
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / f"auto-{todo.id.lower()}.md"
    content = f"""# AUTO-{todo.id}: {todo.title}

**Purpose**: Auto-composed spec by orchestrator (template baseline,
no engine composer).  TODO id: `{todo.id}`.

## Goal

{todo.title}

Notes from STATUS.csv: {todo.notes}

## Acceptance

1. A docs file at `coord/orchestrator-demo/{todo.id}.md` exists.
2. The file contains the TODO id + title + a 1-line ack from the
   orchestrator that the cycle completed.

## Why this spec exists

Phase 3 orchestrator demo cycle.  Tests the path: read STATUS.csv
-> pick TODO -> compose spec -> (optionally) coord run.  Uses a
docs-only deliverable so the demo can't break anything.
"""
    spec_path.write_text(content, encoding="utf-8")
    return spec_path


def fire_coord_run(spec_path: Path, engine: str,
                   fallback_engine: str | None = None,
                   max_seconds: int = 600,
                   no_merge: bool = True) -> dict:
    """Plan + run + watch a spec.  Returns outcome dict."""
    repo_root = Path(__file__).resolve().parents[1]
    env = {**__import__("os").environ, "PYTHONPATH": "src"}

    # Plan
    plan_proc = subprocess.run(
        [sys.executable, "-m", "harness", "coord", "plan",
         "--spec", str(spec_path), "--engine", "claude"],
        capture_output=True, text=True, timeout=120,
        env=env, cwd=str(repo_root),
    )
    if plan_proc.returncode != 0:
        return {"outcome": "plan_failed",
                "stderr": plan_proc.stderr[:500]}

    rid = None
    for line in plan_proc.stdout.splitlines():
        if "plan:" in line and "runs" in line:
            parts = line.split("runs")[-1]
            rid = parts.lstrip("\\/").split("\\")[0].split("/")[0]
            break
    if not rid:
        return {"outcome": "no_run_id",
                "stdout": plan_proc.stdout[:300]}

    # Run with watch
    cmd = [
        sys.executable, "-m", "harness", "coord", "run",
        "--spec", str(spec_path), "--run-id", rid,
        "--engine", engine, "--proxy", "off",
        "--watch", "--watch-interval", "5",
        "--watch-max-seconds", str(max_seconds),
    ]
    if fallback_engine:
        cmd.extend(["--fallback-engine", fallback_engine])
    if no_merge:
        cmd.append("--no-merge")

    run_proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=max_seconds + 60,
        env=env, cwd=str(repo_root),
    )

    # Inspect checkpoints
    run_dir = repo_root / "runs" / rid
    workers_summary: list[dict[str, Any]] = []
    if (run_dir / "checkpoints").exists():
        for ckpt_path in sorted((run_dir / "checkpoints").glob("worker-*.json")):
            try:
                ck = json.loads(ckpt_path.read_text(encoding="utf-8"))
                workers_summary.append({
                    "worker_id": ck.get("worker_id"),
                    "state": ck.get("state"),
                    "files_modified": ck.get("files_modified") or [],
                    "commit_sha": ck.get("commit_sha"),
                })
            except Exception:
                continue

    all_completed = workers_summary and all(
        w["state"] == "completed" for w in workers_summary)
    return {
        "rid": rid,
        "outcome": "completed" if all_completed else "failed",
        "workers": workers_summary,
        "run_exit": run_proc.returncode,
        "stdout_tail": run_proc.stdout[-1000:] if run_proc.stdout else "",
    }


def run_cycle(arch: str,
              composer: Callable[[StatusRow, Path], tuple[Path, str, float]],
              *,
              execute: bool,
              worker_engine: str = "swarm/mimo",
              worker_fallback: str | None = "swarm/deepseek",
              report_dir: Path | None = None) -> CycleResult:
    """One orchestrator cycle.

    Args:
        arch: 'A' / 'B' / 'C' label for the synthesis report.
        composer: callable that takes (StatusRow, spec_dir) and returns
            (spec_path, engine_label, cost_usd).  Each arch plugs in
            its own composer.
        execute: if True, actually fire `coord run --watch`.  If False,
            stop after composing the spec (dry-run).
        worker_engine / worker_fallback: passed to the dispatched
            `coord run` if execute=True.
        report_dir: where to write the cycle's JSON report.  Defaults
            to coord/coverage/.
    """
    started_at_dt = datetime.now(timezone.utc)
    t0 = time.monotonic()
    todo = pick_next_todo()
    spec_path: Path | None = None
    spec_lines = 0
    composer_engine = "n/a"
    composer_cost = 0.0
    executed = False
    exec_outcome: str | None = None
    notes_parts: list[str] = []

    if todo is None:
        notes_parts.append("backlog empty — no TODO to drive")
    else:
        notes_parts.append(f"picked TODO id={todo.id} status={todo.status.value}")
        spec_dir = Path("spec/auto")
        try:
            sp, composer_engine, composer_cost = composer(todo, spec_dir)
            spec_path = sp
            spec_lines = len(sp.read_text(encoding="utf-8").splitlines())
            notes_parts.append(
                f"composed spec via {composer_engine} ({spec_lines} lines, "
                f"${composer_cost:.4f})")
        except Exception as exc:
            notes_parts.append(
                f"composer FAILED: {type(exc).__name__}: {str(exc)[:200]}")

        if spec_path and execute:
            exec_result = fire_coord_run(
                spec_path, engine=worker_engine,
                fallback_engine=worker_fallback,
            )
            executed = True
            exec_outcome = exec_result.get("outcome", "error")
            notes_parts.append(
                f"executed coord run: outcome={exec_outcome} "
                f"workers={len(exec_result.get('workers', []))}")
        elif spec_path:
            exec_outcome = "skipped"
            notes_parts.append("execute=False, spec composed but not run")

    elapsed = time.monotonic() - t0
    result = CycleResult(
        arch=arch,
        started_at=started_at_dt.isoformat(),
        elapsed_s=round(elapsed, 1),
        todo_id=todo.id if todo else None,
        todo_title=todo.title if todo else None,
        spec_path=str(spec_path) if spec_path else None,
        spec_lines=spec_lines,
        composer_engine=composer_engine,
        composer_cost_usd=composer_cost,
        executed=executed,
        execution_outcome=exec_outcome,
        notes="; ".join(notes_parts),
    )

    # Persist report
    rdir = report_dir or Path("coord/coverage")
    rdir.mkdir(parents=True, exist_ok=True)
    stamp = started_at_dt.strftime("%Y%m%dT%H%M%SZ")
    report_path = rdir / f"orchestrator_arch_{arch}_{stamp}.json"
    report_path.write_text(json.dumps(asdict(result), indent=2),
                           encoding="utf-8")
    print(f"\nCycle report: {report_path}", flush=True)
    return result
