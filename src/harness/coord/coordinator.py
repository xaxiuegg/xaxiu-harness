"""Coordinator: orchestrates a spec run across workers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
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


@dataclass
class CoordinationReport:
    run_id: str
    state: RunStateLiteral
    plan_path: Path | None = None
    worker_summary: dict[str, str] = field(default_factory=dict)
    escalations: list[str] = field(default_factory=list)


class Coordinator:
    """Orchestrates a single run from spec → plan → workers → integration."""

    def __init__(self, *, run_id: str, run_dir: str | Path) -> None:
        self.run_id: str = run_id
        self.run_dir: Path = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
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
        completed: set[str] = set()
        for task in plan.tasks:
            ckpt = read_checkpoint(self.run_dir / f"{task.worker_id}.json")
            if ckpt and ckpt.state in ("completed", "failed"):
                completed.add(task.worker_id)

        for task in plan.tasks:
            if in_flight >= limit:
                skipped.append(task.worker_id)
                continue
            if task.worker_id in self._procs and self._procs[task.worker_id].poll() is None:
                continue  # already running
            ckpt = read_checkpoint(self.run_dir / f"{task.worker_id}.json")
            if ckpt and ckpt.state in ("completed", "failed"):
                continue  # already finished

            # Deps check: all deps must be completed
            deps_met = all(dep in completed for dep in task.depends_on or [])
            if not deps_met:
                skipped.append(task.worker_id)
                continue

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
        if not self.run_dir.exists():
            return statuses
        for ckpt_path in self.run_dir.glob("*.json"):
            if ckpt_path.name == "plan.json":
                continue
            if ckpt_path.name == "run_state.json":
                continue
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
        )

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
