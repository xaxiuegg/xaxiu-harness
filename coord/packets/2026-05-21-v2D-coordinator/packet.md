# Packet: v2/D — Coordinator + Integrator + `harness coord` CLI verb group

## Mission

Per `spec/multi-agent-harness-architecture.md` §3.1 + §3.5: implement the Coordinator (drives a run end-to-end), the Integrator (merges worktree branches + final pytest + commit/push), and the `harness coord` CLI verb group that wraps both.

**Depends on v2/B (schemas) and v2/C (worker / worktree / checkpoint).** Tests mock the dispatch + git ops; CI does not actually run a coord run.

## In-scope NEW files

- `src/harness/coord/coordinator.py` — main `Coordinator.run_loop(spec_path, max_workers, ...)` driving the planner → workers → integrator pipeline
- `src/harness/coord/integrator.py` — `integrate(run_dir, strategy='squash') -> IntegrationReport`; merges worker branches, runs full pytest, commits, pushes
- `src/harness/coord/run_state.py` — `read_run_state(path)` / `write_run_state(path, state)` atomic helpers
- `tests/test_coord_coordinator.py`
- `tests/test_coord_integrator.py`
- `tests/test_coord_cli.py`

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group(name="coord")` with subcommands: `run`, `plan`, `work`, `integrate`, `status`. ≤80 LOC; delegate to module.
- `src/harness/coord/__init__.py` — re-export Coordinator + integrate + RunState

## Coordinator skeleton (src/harness/coord/coordinator.py)

```python
from __future__ import annotations
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from harness.coord.schemas import (
    WavePlan, WorkerTask, WorkerStateLiteral, RunState, RunStateLiteral,
    WorkerStatus,
)
from harness.coord.checkpoint import read_checkpoint
from harness.coord.run_state import read_run_state, write_run_state
from harness.coord.worktree import create_worktree, remove_worktree


class Coordinator:
    def __init__(
        self,
        *,
        run_id: str,
        run_dir: Path,
        max_workers: int = 24,
        planner_engine: str = "claude",
        worker_engine: str = "swarm/kimi-api",
        project_root: Path | None = None,
    ):
        self.run_id = run_id
        self.run_dir = run_dir
        self.max_workers = max_workers
        self.planner_engine = planner_engine
        self.worker_engine = worker_engine
        self.project_root = project_root or Path.cwd()

    def ensure_plan(self, spec_path: Path) -> WavePlan:
        plan_path = self.run_dir / "plan.json"
        if plan_path.exists():
            return WavePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        from harness.coord.planner import plan as run_planner, write_plan
        wp = run_planner(
            spec_path,
            run_id=self.run_id,
            engine=self.planner_engine,
            project_root=self.project_root,
        )
        write_plan(wp, self.run_dir)
        return wp

    def launch_workers(self, plan: WavePlan, in_flight_limit: int | None = None) -> dict[str, Any]:
        """For each pending task whose deps are met, launch a worker subprocess."""
        limit = in_flight_limit or self.max_workers
        # ... (subprocess.Popen each worker; track PIDs in run_state)
        return {"launched": [], "skipped": []}

    def poll_workers(self) -> dict[str, WorkerStatus]:
        """Read each worker's checkpoint; classify state."""
        statuses: dict[str, WorkerStatus] = {}
        ckpt_dir = self.run_dir / "checkpoints"
        if not ckpt_dir.exists():
            return statuses
        for ckpt_file in ckpt_dir.glob("worker-*.json"):
            ckpt = read_checkpoint(ckpt_file)
            if ckpt is None:
                continue
            statuses[ckpt.worker_id] = WorkerStatus(
                worker_id=ckpt.worker_id,
                state=WorkerStateLiteral(ckpt.state if ckpt.state in [
                    "pending", "in_progress", "completed", "failed",
                ] else "in_progress"),
                last_checkpoint_at=ckpt.updated_at,
                last_step_id=ckpt.last_completed_step_id,
            )
        return statuses

    def tick(self, spec_path: Path) -> RunState:
        """One tick: ensure plan, poll workers, launch eligible, write state, exit."""
        state_path = self.run_dir / "run.json"
        state = read_run_state(state_path)
        if state is None:
            state = RunState(
                run_id=self.run_id,
                spec_path=str(spec_path),
                state=RunStateLiteral.PLANNING,
                plan_path=str(self.run_dir / "plan.json"),
                started_at=_now_iso(),
                last_tick_at=_now_iso(),
            )
        plan = self.ensure_plan(spec_path)
        state.state = RunStateLiteral.RUNNING
        state.workers = self.poll_workers()
        state.last_tick_at = _now_iso()
        # If all workers completed and integrator hasn't run → mark INTEGRATING
        if state.workers and all(
            w.state == WorkerStateLiteral.COMPLETED for w in state.workers.values()
        ):
            state.state = RunStateLiteral.INTEGRATING
        write_run_state(state_path, state)
        return state


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

## Integrator (src/harness/coord/integrator.py)

```python
from __future__ import annotations
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from harness.coord.schemas import WavePlan, IntegratorStatus

ALLOW_AUTO_INTEGRATE_ENV = "HARNESS_ALLOW_AUTO_INTEGRATE"


@dataclass
class IntegrationReport:
    success: bool
    commit_sha: str | None
    pushed: bool
    test_summary: dict
    diagnostic: str = ""


def integrate(
    run_dir: Path,
    *,
    strategy: str = "squash",
    project_root: Path | None = None,
) -> IntegrationReport:
    repo = project_root or Path.cwd()
    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        return IntegrationReport(False, None, False, {}, "plan.json missing")
    plan = WavePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))

    # Validate all workers completed
    deliv_dir = run_dir / "deliverables"
    completed_workers: list[str] = []
    for task in plan.tasks:
        delv = deliv_dir / f"{task.worker_id}.json"
        if not delv.exists():
            return IntegrationReport(False, None, False, {},
                                      f"missing deliverable for {task.worker_id}")
        data = json.loads(delv.read_text(encoding="utf-8"))
        if data["state"] != "completed":
            return IntegrationReport(False, None, False, {},
                                      f"worker {task.worker_id} state={data['state']}")
        completed_workers.append(task.worker_id)

    # Merge each worktree branch (in worker_id order = a stand-in for dep order)
    for wid in completed_workers:
        branch = f"wt/{plan.run_id}/{wid}"
        result = subprocess.run(
            ["git", "merge", "--no-ff", branch, "-m", f"merge {branch}"],
            cwd=repo, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=repo, check=False)
            return IntegrationReport(
                False, None, False, {},
                f"merge conflict on {branch}: {result.stderr[:500]}",
            )

    # Run full pytest
    test_result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-q", "--tb=line"],
        cwd=repo, capture_output=True, text=True, check=False, timeout=600,
    )
    if test_result.returncode != 0:
        return IntegrationReport(
            False, None, False, {"output": test_result.stdout[:2000]},
            "pytest failed after merge",
        )

    if os.environ.get(ALLOW_AUTO_INTEGRATE_ENV, "").lower() != "true":
        return IntegrationReport(
            True, None, False, {"summary": "ready to commit"},
            "HARNESS_ALLOW_AUTO_INTEGRATE not set; stopping at validation",
        )

    # Commit (squash already happened via merges; do a final no-op commit if needed)
    # Push
    push = subprocess.run(["git", "push", "origin", "master"],
                          cwd=repo, capture_output=True, text=True, check=False)
    commit = subprocess.run(["git", "rev-parse", "HEAD"],
                            cwd=repo, capture_output=True, text=True, check=False)
    return IntegrationReport(
        True, commit.stdout.strip(), push.returncode == 0,
        {"output": test_result.stdout[:500]},
    )
```

## run_state.py

Same atomic-write pattern as `harness.status.store` but for `RunState`.

```python
import os, tempfile
from pathlib import Path
from harness.coord.schemas import RunState

def read_run_state(path: Path) -> RunState | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return RunState.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def write_run_state(path: Path, state: RunState) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".runstate_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(state.model_dump_json(indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
```

## CLI

```python
@cli.group(name="coord")
def coord_group() -> None:
    """Multi-agent coordinator (v2 — planner / worker / integrator)."""

@coord_group.command(name="plan")
@click.option("--spec", required=True, type=click.Path(path_type=Path))
@click.option("--run-id", default=None)
@click.option("--engine", default="claude")
def coord_plan(spec, run_id, engine): ...

@coord_group.command(name="run")
@click.option("--spec", required=True, type=click.Path(path_type=Path))
@click.option("--max-workers", type=int, default=24)
@click.option("--resume", is_flag=True)
def coord_run(spec, max_workers, resume): ...

@coord_group.command(name="work")
@click.option("--run-id", required=True)
@click.option("--worker-id", required=True)
def coord_work(run_id, worker_id): ...

@coord_group.command(name="integrate")
@click.option("--run-id", required=True)
@click.option("--strategy", type=click.Choice(["squash", "merge", "rebase"]), default="squash")
def coord_integrate(run_id, strategy): ...

@coord_group.command(name="status")
@click.option("--run-id", required=True)
def coord_status(run_id): ...
```

## Tests required

coordinator (test_coord_coordinator.py): 6+
- `ensure_plan` loads existing plan.json when present
- `ensure_plan` invokes planner when missing (mock dispatch)
- `tick` transitions RunState through PLANNING → RUNNING → INTEGRATING
- `poll_workers` reads checkpoints + returns WorkerStatus dict
- `launch_workers` respects in_flight_limit

integrator (test_coord_integrator.py): 5+
- Missing plan.json → IntegrationReport(success=False)
- Any worker not completed → IntegrationReport(success=False, diagnostic="worker X state=...")
- Merge conflict (mock git merge to fail) → reports + aborts
- pytest red → reports failure
- ALLOW_AUTO_INTEGRATE=false → stops at "ready to commit"

cli (test_coord_cli.py): 5+
- `harness coord --help` lists 5 subcommands
- `coord plan --spec X` with mocked dispatch produces plan.json
- `coord status --run-id X` reads RunState + prints summary
- `coord run --resume` finds latest run + continues

Target ≥16 new tests.

## Acceptance criteria

1. `harness coord --help` lists 5 subcommands.
2. `harness coord plan --spec spec/X.md --engine claude` produces `runs/<id>/plan.json`.
3. `harness coord status --run-id <id>` shows RunState.
4. `python -m pytest tests/ -q` green.
5. Single commit: `feat(coord): coordinator + integrator + harness coord CLI (v2/D)`.

## Reference

- `spec/multi-agent-harness-architecture.md` §3.1 and §3.5
- `src/harness/coord/schemas.py` (v2/B) — imported types
- `src/harness/coord/worker.py` and `worktree.py` (v2/C) — siblings
- `src/harness/loops/runner.py` — pattern reference for tick()
- `src/harness/status/store.py` — atomic-write pattern

## Output format

6 new files + 1 cli.py modification (≤80 LOC) + 1 init.py modification + 1 commit.
