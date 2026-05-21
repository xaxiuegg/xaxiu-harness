"""Coordinator: orchestrates a spec run across workers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.coord.checkpoint import Checkpoint, read_checkpoint
from harness.coord.planner import plan as run_planner, write_plan
from harness.coord.run_state import read_run_state, write_run_state
from harness.coord.schemas import (
    IntegratorStatus,
    RunState,
    RunStateLiteral,
    WavePlan,
    WorkerStateLiteral,
    WorkerStatus,
)
from harness.coord.worktree import create_worktree


@dataclass
class CoordinationReport:
    run_id: str
    state: RunStateLiteral
    plan_path: Path | None = None
    worker_summary: dict[str, str] = field(default_factory=dict)
    escalations: list[str] = field(default_factory=list)


class Coordinator:
    """Orchestrates a single run from spec → plan → workers → integration."""

    def __init__(self, *, run_id: str, run_dir: str | Path, project_root: Path | None = None,
                 label: str | None = None) -> None:
        self.run_id: str = run_id
        self.run_dir: Path = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.project_root: Path = project_root or Path.cwd()
        self.label: str | None = label
        self._procs: dict[str, subprocess.Popen] = {}

    @property
    def state_path(self) -> Path:
        return self.run_dir / "run_state.json"

    @property
    def plan_path(self) -> Path:
        return self.run_dir / "plan.json"

    # ------------------------------------------------------------------ #
    # plan
    # ------------------------------------------------------------------ #

    def ensure_plan(
        self,
        spec_path: Path,
        *,
        engine: str = "kimi",
        model: str | None = None,
        project_root: Path | None = None,
        max_retries: int = 2,
    ) -> WavePlan:
        if self.plan_path.exists():
            plan_obj = WavePlan.model_validate_json(self.plan_path.read_text(encoding="utf-8"))
            state = read_run_state(self.state_path)
            if state is not None:
                state.plan_path = str(self.plan_path)
                write_run_state(self.state_path, state)
            return plan_obj

        plan_obj = run_planner(
            spec_path,
            run_id=self.run_id,
            engine=engine,
            model=model,
            project_root=project_root or Path.cwd(),
            max_retries=max_retries,
        )
        write_plan(plan_obj, self.run_dir)
        return plan_obj

    # ------------------------------------------------------------------ #
    # workers
    # ------------------------------------------------------------------ #

    def launch_workers(self, plan: WavePlan, in_flight_limit: int | None = None) -> dict[str, Any]:
        """Spawn worker processes up to *in_flight_limit*."""
        limit = in_flight_limit or 4
        launched: list[str] = []
        skipped: list[str] = []

        # Count currently in-flight from our tracked processes
        in_flight = sum(
            1 for p in self._procs.values() if p.poll() is None
        )

        # Gather completed workers from checkpoints
        checkpoints_dir = self.run_dir / "checkpoints"
        completed: set[str] = set()
        for task in plan.tasks:
            ckpt = read_checkpoint(checkpoints_dir / f"{task.worker_id}.json")
            if ckpt and ckpt.state in ("completed", "failed"):
                completed.add(task.worker_id)

        for task in plan.tasks:
            if in_flight >= limit:
                skipped.append(task.worker_id)
                continue
            if task.worker_id in self._procs and self._procs[task.worker_id].poll() is None:
                continue  # already running
            ckpt = read_checkpoint(checkpoints_dir / f"{task.worker_id}.json")
            if ckpt and ckpt.state in ("completed", "failed"):
                continue  # already finished

            # Deps check: all deps must be completed
            deps_met = all(dep in completed for dep in task.depends_on or [])
            if not deps_met:
                skipped.append(task.worker_id)
                continue

            # Create worktree before spawning worker
            create_worktree(
                self.run_id,
                task.worker_id,
                base_branch="master",
                repo_root=self.project_root,
            )

            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "coord",
                    "work",
                    "--run-id",
                    self.run_id,
                    "--worker-id",
                    task.worker_id,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._procs[task.worker_id] = proc
            launched.append(task.worker_id)
            in_flight += 1

        return {"launched": launched, "skipped": skipped}

    def poll_workers(self) -> dict[str, WorkerStatus]:
        """Read every worker checkpoint and return status map."""
        statuses: dict[str, WorkerStatus] = {}
        checkpoints_dir = self.run_dir / "checkpoints"
        if not checkpoints_dir.exists():
            return statuses
        for ckpt_path in checkpoints_dir.glob("*.json"):
            ckpt = read_checkpoint(ckpt_path)
            if ckpt is None:
                continue
            wid = ckpt.worker_id or ckpt_path.stem
            state_str = ckpt.state
            try:
                state_val = WorkerStateLiteral(state_str)
            except ValueError:
                state_val = WorkerStateLiteral.IN_PROGRESS
            pid = None
            if wid in self._procs:
                pid = self._procs[wid].pid
            statuses[wid] = WorkerStatus(
                worker_id=wid,
                state=state_val,
                last_checkpoint_at=ckpt.updated_at or "",
                last_step_id=ckpt.last_completed_step_id,
                pid=pid,
            )
        return statuses

    # ------------------------------------------------------------------ #
    # tick
    # ------------------------------------------------------------------ #

    def tick(self, spec_path: Path, *, in_flight_limit: int | None = None) -> CoordinationReport:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        state = read_run_state(self.state_path) or RunState(
            schema_version=1,
            run_id=self.run_id,
            spec_path=str(spec_path),
            state=RunStateLiteral.PLANNING,
            plan_path=str(self.plan_path) if self.plan_path.exists() else "",
            started_at=now,
            last_tick_at=now,
            workers={},
            integrator_status=IntegratorStatus(state="pending"),
            escalations=[],
            label=self.label,
        )
        # If the run was resumed and the operator passed a new label, update it
        if self.label and state.label != self.label:
            state.label = self.label

        # PLANNING -> RUNNING
        if state.state == RunStateLiteral.PLANNING:
            plan_obj = self.ensure_plan(spec_path)
            state.plan_path = str(self.plan_path)
            state.state = RunStateLiteral.RUNNING
            write_run_state(self.state_path, state)
            return CoordinationReport(
                run_id=self.run_id,
                state=state.state,
                plan_path=self.plan_path,
            )

        # RUNNING -> check workers
        if state.state == RunStateLiteral.RUNNING:
            plan_obj = WavePlan.model_validate_json(self.plan_path.read_text(encoding="utf-8"))
            self.launch_workers(plan_obj, in_flight_limit=in_flight_limit)
            statuses = self.poll_workers()
            state.workers = statuses
            state.last_tick_at = now

            # Check if all workers completed or failed
            all_done = all(
                st.state in (WorkerStateLiteral.COMPLETED, WorkerStateLiteral.FAILED)
                for st in statuses.values()
            )
            has_workers = len(plan_obj.tasks) > 0
            all_accounted = len(statuses) == len(plan_obj.tasks)
            if has_workers and all_done and all_accounted:
                state.state = RunStateLiteral.INTEGRATING

            write_run_state(self.state_path, state)
            return CoordinationReport(
                run_id=self.run_id,
                state=state.state,
                plan_path=self.plan_path,
                worker_summary={wid: str(st.state.value) for wid, st in statuses.items()},
            )

        # INTEGRATING / COMPLETED / FAILED — no-op tick
        state.last_tick_at = now
        write_run_state(self.state_path, state)
        return CoordinationReport(
            run_id=self.run_id,
            state=state.state,
            plan_path=self.plan_path,
            worker_summary={wid: str(st.state.value) for wid, st in state.workers.items()},
        )


def detect_stalled_workers(
    run_dir: Path,
    *,
    max_silence_seconds: int = 600,
    now: datetime | None = None,
) -> list[str]:
    """Return worker_ids whose heartbeat file is older than max_silence_seconds.

    A missing heartbeat is treated as "no heartbeat yet" — only counts as
    stalled if the corresponding checkpoint is state="in_progress".
    """
    import time
    from datetime import datetime, timezone
    from harness.coord.checkpoint import read_checkpoint

    now_dt = now or datetime.now(timezone.utc)
    stalled: list[str] = []
    ckpt_dir = run_dir / "checkpoints"
    if not ckpt_dir.exists():
        return stalled

    for ckpt_path in sorted(ckpt_dir.glob("*.json")):
        ckpt = read_checkpoint(ckpt_path)
        if ckpt is None or ckpt.state != "in_progress":
            continue
        hb_path = ckpt_dir / f"{ckpt.worker_id}.heartbeat"
        if not hb_path.exists():
            # No heartbeat yet — count as stalled only if checkpoint is
            # also older than the silence window (otherwise it might just
            # have just started)
            try:
                age = now_dt.timestamp() - ckpt_path.stat().st_mtime
            except OSError:
                age = 0
            if age > max_silence_seconds:
                stalled.append(ckpt.worker_id)
            continue
        try:
            hb_age = now_dt.timestamp() - hb_path.stat().st_mtime
        except OSError:
            continue
        if hb_age > max_silence_seconds:
            stalled.append(ckpt.worker_id)
    return stalled


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------

_ACTIVE_STATES = frozenset({RunStateLiteral.PLANNING, RunStateLiteral.RUNNING, RunStateLiteral.INTEGRATING})


@dataclass
class CleanupReport:
    runs_removed: list[str]
    worktrees_removed: list[str]
    bytes_freed: int
    skipped_active: list[str]
    dry_run: bool


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _dir_size(Path(entry.path))
    except OSError:
        pass
    return total


def _remove_worktrees_for_run(
    run_id: str,
    repo_root: Path,
    dry_run: bool,
) -> tuple[list[str], int]:
    removed: list[str] = []
    bytes_freed = 0
    wt_run_dir = repo_root / ".harness" / "worktrees" / run_id
    if not wt_run_dir.exists():
        return removed, bytes_freed

    for worker_dir in sorted(wt_run_dir.iterdir()):
        if not worker_dir.is_dir():
            continue
        bytes_freed += _dir_size(worker_dir)
        removed.append(str(worker_dir))
        if not dry_run:
            subprocess.run(
                ["git", "worktree", "remove", str(worker_dir), "--force"],
                check=False,
                cwd=repo_root,
                capture_output=True,
            )

    bytes_freed += _dir_size(wt_run_dir)
    if not dry_run:
        shutil.rmtree(wt_run_dir, ignore_errors=True)

    return removed, bytes_freed


def cleanup_run(
    run_id: str,
    *,
    repo_root: Path | None = None,
    keep_deliverables: bool = False,
    dry_run: bool = False,
) -> CleanupReport:
    repo = repo_root or Path.cwd()
    run_dir = repo / "runs" / run_id
    state_path = run_dir / "run_state.json"

    state = read_run_state(state_path) if state_path.exists() else None
    if state is not None and state.state in _ACTIVE_STATES:
        return CleanupReport(
            runs_removed=[],
            worktrees_removed=[],
            bytes_freed=0,
            skipped_active=[run_id],
            dry_run=dry_run,
        )

    bytes_freed = 0
    worktrees_removed: list[str] = []
    runs_removed: list[str] = []

    # Worktrees
    wts, wt_bytes = _remove_worktrees_for_run(run_id, repo, dry_run)
    worktrees_removed.extend(wts)
    bytes_freed += wt_bytes

    # Run directory
    if run_dir.exists():
        if keep_deliverables:
            checkpoints_dir = run_dir / "checkpoints"
            if checkpoints_dir.exists():
                bytes_freed += _dir_size(checkpoints_dir)
                if not dry_run:
                    shutil.rmtree(checkpoints_dir, ignore_errors=True)

            rs_path = run_dir / "run_state.json"
            if rs_path.exists():
                bytes_freed += rs_path.stat().st_size
                if not dry_run:
                    rs_path.unlink(missing_ok=True)

            for ckpt in run_dir.glob("*.json"):
                if ckpt.name == "plan.json":
                    continue
                bytes_freed += ckpt.stat().st_size
                if not dry_run:
                    ckpt.unlink(missing_ok=True)

            runs_removed.append(run_id)
        else:
            bytes_freed += _dir_size(run_dir)
            if not dry_run:
                shutil.rmtree(run_dir, ignore_errors=True)
            runs_removed.append(run_id)

    return CleanupReport(
        runs_removed=runs_removed,
        worktrees_removed=worktrees_removed,
        bytes_freed=bytes_freed,
        skipped_active=[],
        dry_run=dry_run,
    )


def cleanup_all_completed(
    *,
    repo_root: Path | None = None,
    keep_deliverables: bool = False,
    dry_run: bool = False,
) -> CleanupReport:
    repo = repo_root or Path.cwd()
    runs_dir = repo / "runs"

    report = CleanupReport(
        runs_removed=[],
        worktrees_removed=[],
        bytes_freed=0,
        skipped_active=[],
        dry_run=dry_run,
    )

    if not runs_dir.exists():
        return report

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        sub = cleanup_run(
            run_id,
            repo_root=repo,
            keep_deliverables=keep_deliverables,
            dry_run=dry_run,
        )
        report.runs_removed.extend(sub.runs_removed)
        report.worktrees_removed.extend(sub.worktrees_removed)
        report.bytes_freed += sub.bytes_freed
        report.skipped_active.extend(sub.skipped_active)

    return report
