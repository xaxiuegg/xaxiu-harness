"""W5-T: autonomous orchestrator daemon — Path α implementation.

Wraps `scripts/orchestrator_c_hybrid.py` (Arch C: MiMo primary + DeepSeek
fallback + template last-resort) in a loop that can be invoked
directly OR scheduled via Windows Task Scheduler.

Merge policy (operator directive 2026-05-23):
  - Worker completes + tests_passed=true  → integrate with merge + commit
  - Worker fails OR tests fail            → --no-merge, leave worktree
                                              for manual review

Concretely the orchestrator runs one or more cycles, each:
  1. Pick next TODO from coord/STATUS.csv
  2. Compose a spec via MiMo Pro (Arch C hybrid composer)
  3. Fire `coord run --watch --no-merge` (validate worktree)
  4. If all workers completed + tests passed → coord integrate --commit
  5. Update coord/STATUS.csv row
  6. Report cycle outcome to coord/coverage/orchestrator_cycle_<stamp>.json

CLI:
    harness orchestrator start         # run forever (or until backlog empty)
    harness orchestrator start --once  # single cycle
    harness orchestrator start --max-cycles 5  # cap iterations
    harness orchestrator install-scheduler  # add Windows Task Scheduler entry
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CycleOutcome:
    cycle: int
    started_at: str
    elapsed_s: int
    todo_id: str | None
    composer_engine: str
    composer_cost_usd: float
    run_id: str | None
    worker_outcome: str  # 'completed' / 'failed' / 'no_workers' / 'skipped'
    tests_passed: bool
    merged: bool
    diagnostic: str = ""


def _safe_run(cmd: list[str], timeout: int, cwd: Path) -> tuple[int, str, str]:
    """Run a subprocess; return (rc, stdout, stderr).  Never raises."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=str(cwd),
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "(timeout)"
    except Exception as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"


def run_one_cycle(cycle: int, *, dry_run: bool = False,
                  repo_root: Path | None = None) -> CycleOutcome:
    """One orchestrator cycle: compose spec → run → conditionally merge.

    Args:
        cycle: integer for the cycle number (for the report filename).
        dry_run: if True, skip the actual coord run + integrate.
        repo_root: repo root path (defaults to cwd).
    """
    started_at_dt = datetime.now(timezone.utc)
    t0 = time.monotonic()
    repo = repo_root or Path.cwd()

    # 1. Invoke the Arch C hybrid orchestrator script to compose a spec
    # and (if execute=True) run the coord cycle with --no-merge.
    compose_cmd = [
        sys.executable,
        str(repo / "scripts" / "orchestrator_c_hybrid.py"),
    ]
    if not dry_run:
        compose_cmd.append("--execute")
    rc, stdout, stderr = _safe_run(compose_cmd, timeout=900, cwd=repo)

    # Parse the cycle report the script wrote.  Naive: pick the newest
    # orchestrator_arch_C_*.json.
    coverage_dir = repo / "coord" / "coverage"
    cycle_reports = sorted(
        coverage_dir.glob("orchestrator_arch_C_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not cycle_reports:
        return CycleOutcome(
            cycle=cycle,
            started_at=started_at_dt.isoformat(),
            elapsed_s=int(time.monotonic() - t0),
            todo_id=None, composer_engine="n/a", composer_cost_usd=0.0,
            run_id=None, worker_outcome="no_workers",
            tests_passed=False, merged=False,
            diagnostic=f"orchestrator_c_hybrid.py rc={rc} no report produced",
        )

    try:
        report = json.loads(cycle_reports[0].read_text(encoding="utf-8"))
    except Exception as exc:
        return CycleOutcome(
            cycle=cycle,
            started_at=started_at_dt.isoformat(),
            elapsed_s=int(time.monotonic() - t0),
            todo_id=None, composer_engine="n/a", composer_cost_usd=0.0,
            run_id=None, worker_outcome="no_workers",
            tests_passed=False, merged=False,
            diagnostic=f"cycle report unparseable: {exc}",
        )

    todo_id = report.get("todo_id")
    composer = report.get("composer_engine", "n/a")
    composer_cost = float(report.get("composer_cost_usd", 0.0))
    worker_outcome = report.get("execution_outcome", "skipped")
    if not report.get("executed", False):
        return CycleOutcome(
            cycle=cycle,
            started_at=started_at_dt.isoformat(),
            elapsed_s=int(time.monotonic() - t0),
            todo_id=todo_id, composer_engine=composer,
            composer_cost_usd=composer_cost,
            run_id=None, worker_outcome="skipped",
            tests_passed=False, merged=False,
            diagnostic="dry-run mode (no coord run fired)",
        )

    # Find the most-recent run dir to inspect tests
    runs_dir = repo / "runs"
    if not runs_dir.exists():
        return CycleOutcome(
            cycle=cycle,
            started_at=started_at_dt.isoformat(),
            elapsed_s=int(time.monotonic() - t0),
            todo_id=todo_id, composer_engine=composer,
            composer_cost_usd=composer_cost,
            run_id=None, worker_outcome=worker_outcome,
            tests_passed=False, merged=False,
            diagnostic="no runs/ dir after coord run",
        )

    latest_run = max(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime)
    run_id = latest_run.name
    ckpts_dir = latest_run / "checkpoints"
    worker_states = []
    all_tests_passed = True
    if ckpts_dir.exists():
        for ckpt_path in sorted(ckpts_dir.glob("worker-*.json")):
            try:
                ck = json.loads(ckpt_path.read_text(encoding="utf-8"))
                worker_states.append((ck.get("state"), ck.get("tests_passed", False)))
                if not ck.get("tests_passed", False):
                    all_tests_passed = False
            except Exception:
                all_tests_passed = False

    all_completed = bool(worker_states) and all(
        st == "completed" for st, _ in worker_states)
    should_merge = all_completed and all_tests_passed

    # 2. If should_merge, fire integrate WITH merge (and commit, no push)
    merged = False
    diag_parts = [
        f"workers={len(worker_states)}",
        f"all_completed={all_completed}",
        f"tests_passed={all_tests_passed}",
        f"should_merge={should_merge}",
    ]
    if should_merge and not dry_run:
        integrate_cmd = [
            sys.executable, "-m", "harness", "coord", "integrate",
            "--run-id", run_id, "--commit",
        ]
        rc_int, out_int, err_int = _safe_run(integrate_cmd, timeout=900, cwd=repo)
        merged = rc_int == 0
        diag_parts.append(f"integrate_rc={rc_int}")
        if not merged:
            diag_parts.append(f"integrate_stderr={err_int[:200]}")

    outcome = CycleOutcome(
        cycle=cycle,
        started_at=started_at_dt.isoformat(),
        elapsed_s=int(time.monotonic() - t0),
        todo_id=todo_id, composer_engine=composer,
        composer_cost_usd=composer_cost,
        run_id=run_id, worker_outcome=worker_outcome,
        tests_passed=all_tests_passed, merged=merged,
        diagnostic="; ".join(diag_parts),
    )

    # Persist
    stamp = started_at_dt.strftime("%Y%m%dT%H%M%SZ")
    out_path = coverage_dir / f"orchestrator_cycle_{cycle:03d}_{stamp}.json"
    out_path.write_text(json.dumps(asdict(outcome), indent=2), encoding="utf-8")
    return outcome


def run_loop(*, max_cycles: int | None = None,
             interval_seconds: int = 0,
             dry_run: bool = False) -> list[CycleOutcome]:
    """Run cycles until backlog empty OR max_cycles reached.

    Args:
        max_cycles: cap on iterations.  None = unlimited.
        interval_seconds: sleep between cycles (for cron-like cadence).
        dry_run: skip coord run + integrate.
    """
    outcomes: list[CycleOutcome] = []
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        cycle += 1
        print(f"\n{'='*60}\n=== Orchestrator cycle {cycle} ===\n{'='*60}",
              flush=True)
        outcome = run_one_cycle(cycle, dry_run=dry_run)
        outcomes.append(outcome)
        print(f"\nCycle {cycle} outcome: {outcome.worker_outcome} "
              f"merged={outcome.merged} elapsed={outcome.elapsed_s}s "
              f"cost=${outcome.composer_cost_usd:.4f}", flush=True)
        if outcome.todo_id is None:
            print("\nBacklog empty.  Stopping loop.", flush=True)
            break
        if interval_seconds > 0 and (max_cycles is None or cycle < max_cycles):
            print(f"\nSleeping {interval_seconds}s before next cycle...",
                  flush=True)
            time.sleep(interval_seconds)
    return outcomes
