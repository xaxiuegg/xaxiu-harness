# COORD-RERUN-FAILED — `harness coord rerun-failed <run_id>` chain replan+run+integrate

## Goal

When a run fails, the operator currently has to type 3 commands in
sequence: `coord replan`, `coord run`, `coord integrate`.  This wave
chains them into one verb so failure recovery is a single call.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New CLI subcommand inside `coord` group

In `src/harness/cli.py`, find `@coord_group.command(name="replan")`
(added earlier this session) and add a NEW command IMMEDIATELY AFTER:

```python
@coord_group.command(name="rerun-failed")
@click.option("--run-id", required=True, help="Run ID of the failed run.")
@click.option("--engine", default="claude", help="Planner engine for replan.")
@click.option("--worker-engine", default="swarm/kimi-api",
              help="Engine for the new workers.")
@click.option("--auto-integrate", is_flag=True,
              help="Also run integrate after the new workers complete.")
def coord_rerun_failed(run_id: str, engine: str, worker_engine: str,
                       auto_integrate: bool) -> None:
    """Chain replan → run → (optional) integrate for a failed run."""
    from harness.coord.planner import replan_from_run, write_plan
    from harness.coord.coordinator import Coordinator
    from harness.coord.integrator import integrate

    failed_dir = Path("runs") / run_id
    if not failed_dir.exists():
        click.echo(f"error: no such run {run_id}", err=True)
        sys.exit(1)

    # Step 1: replan
    try:
        new_plan = replan_from_run(failed_dir, engine=engine)
    except FileNotFoundError as exc:
        click.echo(f"error during replan: {exc}", err=True)
        sys.exit(1)
    new_run_dir = Path("runs") / new_plan.run_id
    write_plan(new_plan, new_run_dir)
    click.echo(f"replan: new run_id={new_plan.run_id} with {len(new_plan.tasks)} task(s)")

    # Step 2: coord.tick — pass the original spec path from the new plan
    coord = Coordinator(run_id=new_plan.run_id, run_dir=new_run_dir)
    report = coord.tick(Path(new_plan.spec_path))
    click.echo(f"run: state={report.state.value}")
    for wid, st in (report.worker_summary or {}).items():
        click.echo(f"  {wid}: {st}")

    if not auto_integrate:
        sys.exit(0 if report.state.value in ("completed", "running") else 1)

    # Step 3: integrate (only when --auto-integrate)
    irep = integrate(new_run_dir)
    click.echo(f"integrate: success={irep.success} merged={len(irep.workers_merged)} "
               f"conflicted={len(irep.workers_conflicted)}")
    sys.exit(0 if irep.success else 1)
```

### 2. Tests

`tests/test_coord_rerun_failed.py`:

```python
"""Tests for COORD-RERUN-FAILED."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep


def _make_wp(run_id: str, spec_path: str) -> WavePlan:
    return WavePlan(
        run_id=run_id, spec_path=spec_path,
        created_at="2026-05-21T00:00:00+00:00",
        planner_engine="mock",
        tasks=[WorkerTask(
            worker_id="worker-1", title="t", description="d",
            steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                              target_files=["x.txt"], expected_diff_lines=1)],
        )],
    )


def test_rerun_failed_unknown_run(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["coord", "rerun-failed", "--run-id", "nope"])
    assert result.exit_code == 1
    assert "no such run" in result.output


def test_rerun_failed_chains_replan_and_run(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        old_run_dir = iso_path / "runs" / "20260521T000000-aabb"
        old_run_dir.mkdir(parents=True)
        spec = iso_path / "spec.md"
        spec.write_text("# spec\n", encoding="utf-8")

        with patch("harness.coord.planner.replan_from_run") as mock_re, \
             patch("harness.coord.planner.write_plan") as mock_w, \
             patch("harness.coord.coordinator.Coordinator") as mock_coord:
            mock_re.return_value = _make_wp("20260521T010000-cccc", str(spec))
            mock_w.return_value = iso_path / "runs" / "20260521T010000-cccc" / "plan.json"
            mock_coord.return_value.tick.return_value = MagicMock(
                run_id="20260521T010000-cccc",
                state=MagicMock(value="running"),
                worker_summary={"worker-1": "completed"},
            )
            result = runner.invoke(cli, [
                "coord", "rerun-failed",
                "--run-id", "20260521T000000-aabb",
                "--engine", "mock",
            ])

    assert result.exit_code == 0, result.output
    assert "20260521T010000-cccc" in result.output
    assert "worker-1: completed" in result.output


def test_rerun_failed_auto_integrate(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        (iso_path / "runs" / "20260521T000000-aabb").mkdir(parents=True)
        spec = iso_path / "spec.md"
        spec.write_text("# spec\n", encoding="utf-8")

        with patch("harness.coord.planner.replan_from_run") as mock_re, \
             patch("harness.coord.planner.write_plan") as mock_w, \
             patch("harness.coord.coordinator.Coordinator") as mock_coord, \
             patch("harness.coord.integrator.integrate") as mock_int:
            mock_re.return_value = _make_wp("20260521T010000-cccc", str(spec))
            mock_w.return_value = iso_path / "runs" / "20260521T010000-cccc" / "plan.json"
            mock_coord.return_value.tick.return_value = MagicMock(
                run_id="20260521T010000-cccc",
                state=MagicMock(value="completed"),
                worker_summary={},
            )
            mock_int.return_value = MagicMock(
                success=True, workers_merged=["worker-1"], workers_conflicted=[],
            )
            result = runner.invoke(cli, [
                "coord", "rerun-failed",
                "--run-id", "20260521T000000-aabb",
                "--auto-integrate",
            ])

    assert result.exit_code == 0, result.output
    assert "integrate: success=True" in result.output
```

## Acceptance

- `python -m pytest tests/test_coord_rerun_failed.py` — green.
- Full suite stays green.
- `harness coord rerun-failed --help` shows the new verb.

## Constraints

- DO NOT modify replan_from_run, Coordinator, or integrate.
- DO NOT touch any other CLI command.
- Stdlib only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
