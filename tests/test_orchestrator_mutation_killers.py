"""W7-MUTATION-ORCH: real-assertion tests that kill orchestrator.py
mutations the W6-A3 sweep found (0.0 kill rate).

The W6-A3 sweep applied 2 mutations to orchestrator.py:
  - eq_to_neq         (line 170:  `st == "completed"` in the all-
                       completed determination)
  - gt_to_ge          (line 234:  `interval_seconds > 0` in run_loop)

Both came back failed=0.  The eq_to_neq mutation is observable
(merge gating inverts); gt_to_ge is semantically benign because
`time.sleep(0)` returns immediately, same as not sleeping at all.

This file targets the catchable mutations directly:
  - 5 tests on the merge-gating logic (line 170 `st == "completed"`)
  - 3 tests on the integrate-success check (line 187 `rc_int == 0`,
    a secondary eq_to_neq mutation if the script's first-occurrence
    ever shifts)
  - 1 test on run_loop's backlog-empty exit
  - 1 test on dry_run gating

Tests mock _safe_run + filesystem so they're hermetic + fast.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.orchestrator import run_one_cycle, run_loop, CycleOutcome


def _setup_run_dir(tmp_path: Path, *,
                   worker_checkpoints: list[dict] | None = None,
                   cycle_report: dict | None = None) -> Path:
    """Build a synthetic run dir + cycle report so run_one_cycle finds
    them without invoking the real orchestrator_c_hybrid.py."""
    repo = tmp_path
    (repo / "coord" / "coverage").mkdir(parents=True, exist_ok=True)
    (repo / "runs" / "20260523T-orch-test" / "checkpoints").mkdir(
        parents=True, exist_ok=True
    )
    # Cycle report from the composer step
    if cycle_report is None:
        cycle_report = {
            "todo_id": "TASK-1",
            "composer_engine": "mimo",
            "composer_cost_usd": 0.05,
            "executed": True,
            "execution_outcome": "completed",
        }
    (repo / "coord" / "coverage" / "orchestrator_arch_C_20260523T-orch-test.json"
     ).write_text(json.dumps(cycle_report), encoding="utf-8")

    # Worker checkpoints
    if worker_checkpoints is None:
        worker_checkpoints = [
            {"worker_id": "worker-1", "state": "completed",
             "tests_passed": True}
        ]
    for i, ck in enumerate(worker_checkpoints):
        path = (repo / "runs" / "20260523T-orch-test" / "checkpoints"
                / f"worker-{i+1}.json")
        path.write_text(json.dumps(ck), encoding="utf-8")
    return repo


# ===========================================================================
# Kill `st == "completed"` mutation (line 170) — merge gating
# ===========================================================================


def test_all_workers_completed_triggers_should_merge(
    tmp_path: Path,
) -> None:
    """Mutation: `st == "completed"` → `!= "completed"`.

    Under the mutation, all_completed=True would become FALSE when
    workers ARE in completed state — blocking merges that should
    fire."""
    repo = _setup_run_dir(tmp_path, worker_checkpoints=[
        {"state": "completed", "tests_passed": True},
        {"state": "completed", "tests_passed": True},
    ])

    # Stub _safe_run: composer returns rc=0 (success), integrate also rc=0
    with patch("harness.orchestrator._safe_run", return_value=(0, "", "")):
        outcome = run_one_cycle(1, repo_root=repo)
    assert outcome.merged is True, (
        f"with 2 completed + tests-passed workers, merge should fire; "
        f"outcome.merged={outcome.merged} diag={outcome.diagnostic!r}"
    )
    assert "all_completed=True" in outcome.diagnostic


def test_one_failed_worker_blocks_merge(
    tmp_path: Path,
) -> None:
    """Mutation: under `!= "completed"` mutation, a failed worker would
    flip all_completed to True (because failed != completed), and merge
    would fire when it shouldn't."""
    repo = _setup_run_dir(tmp_path, worker_checkpoints=[
        {"state": "completed", "tests_passed": True},
        {"state": "failed", "tests_passed": False},
    ])

    with patch("harness.orchestrator._safe_run", return_value=(0, "", "")):
        outcome = run_one_cycle(1, repo_root=repo)
    assert outcome.merged is False, (
        f"failed worker must block merge; outcome.merged={outcome.merged} "
        f"diag={outcome.diagnostic!r}"
    )
    assert "all_completed=False" in outcome.diagnostic


def test_in_progress_worker_blocks_merge(
    tmp_path: Path,
) -> None:
    """A worker stuck in_progress must also block merge."""
    repo = _setup_run_dir(tmp_path, worker_checkpoints=[
        {"state": "in_progress", "tests_passed": False},
    ])

    with patch("harness.orchestrator._safe_run", return_value=(0, "", "")):
        outcome = run_one_cycle(1, repo_root=repo)
    assert outcome.merged is False
    assert "all_completed=False" in outcome.diagnostic


def test_empty_worker_list_blocks_merge(
    tmp_path: Path,
) -> None:
    """No worker checkpoints → all_completed must be False (the
    `bool(worker_states)` guard).  Important sentinel: under any
    mutation that flips the empty-list check, merge could fire on
    a totally-empty run.  This is a separate hardening test."""
    repo = _setup_run_dir(tmp_path, worker_checkpoints=[])

    with patch("harness.orchestrator._safe_run", return_value=(0, "", "")):
        outcome = run_one_cycle(1, repo_root=repo)
    assert outcome.merged is False
    assert "workers=0" in outcome.diagnostic
    assert "all_completed=False" in outcome.diagnostic


def test_all_completed_but_tests_failed_blocks_merge(
    tmp_path: Path,
) -> None:
    """all_completed=True alone is insufficient — tests_passed must
    also be True.  Under a mutation that drops the conjunction,
    merge would fire on test failure."""
    repo = _setup_run_dir(tmp_path, worker_checkpoints=[
        {"state": "completed", "tests_passed": False},
    ])

    with patch("harness.orchestrator._safe_run", return_value=(0, "", "")):
        outcome = run_one_cycle(1, repo_root=repo)
    assert outcome.merged is False
    # all_completed is True but tests aren't, so should_merge is False
    assert "all_completed=True" in outcome.diagnostic
    assert "tests_passed=False" in outcome.diagnostic
    assert "should_merge=False" in outcome.diagnostic


# ===========================================================================
# Kill `rc_int == 0` mutation (line 187) — integrate success check
# ===========================================================================


def test_integrate_rc_zero_marks_merged_true(
    tmp_path: Path,
) -> None:
    """Mutation: `rc_int == 0` → `!= 0`.  Under the mutation, integrate
    success would flip to merged=False."""
    repo = _setup_run_dir(tmp_path)  # default: 1 completed worker
    # Sequential _safe_run calls: composer (rc=0), integrate (rc=0)
    call_count = {"n": 0}

    def _safe_run_stub(cmd, **kwargs):
        call_count["n"] += 1
        return (0, "ok", "")

    with patch("harness.orchestrator._safe_run", side_effect=_safe_run_stub):
        outcome = run_one_cycle(1, repo_root=repo)
    assert outcome.merged is True
    assert "integrate_rc=0" in outcome.diagnostic
    assert call_count["n"] >= 2  # composer + integrate


def test_integrate_rc_nonzero_marks_merged_false(
    tmp_path: Path,
) -> None:
    """Mutation: under `rc_int != 0`, an integrate failure (rc=1) would
    set merged=True.  Verify rc=1 produces merged=False."""
    repo = _setup_run_dir(tmp_path)
    call_count = {"n": 0}

    def _safe_run_stub(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (0, "ok", "")  # composer succeeds
        return (1, "", "integrate broke")  # integrate fails

    with patch("harness.orchestrator._safe_run", side_effect=_safe_run_stub):
        outcome = run_one_cycle(1, repo_root=repo)
    assert outcome.merged is False, (
        f"integrate rc=1 must set merged=False; got {outcome.merged}"
    )
    assert "integrate_rc=1" in outcome.diagnostic


def test_integrate_failure_diagnostic_includes_stderr(
    tmp_path: Path,
) -> None:
    """Sentinel: when integrate fails, the stderr is preserved in the
    diagnostic for operator triage."""
    repo = _setup_run_dir(tmp_path)
    call_count = {"n": 0}

    def _safe_run_stub(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (0, "ok", "")
        return (5, "", "specific stderr error message here")

    with patch("harness.orchestrator._safe_run", side_effect=_safe_run_stub):
        outcome = run_one_cycle(1, repo_root=repo)
    assert outcome.merged is False
    assert "specific stderr error message" in outcome.diagnostic


# ===========================================================================
# run_loop control flow — kill any plus1 / off-by-one mutations
# ===========================================================================


def test_run_loop_stops_when_backlog_empty(monkeypatch) -> None:
    """run_loop must exit early when run_one_cycle returns todo_id=None
    (backlog empty signal).  Under mutations that flip the None check,
    the loop could infinite-loop."""
    counts = {"n": 0}

    def _fake_run_one_cycle(cycle, dry_run=False, repo_root=None):
        counts["n"] += 1
        # Return a synthetic outcome with todo_id=None to signal stop
        return CycleOutcome(
            cycle=cycle, started_at="t", elapsed_s=0,
            todo_id=None, composer_engine="mimo",
            composer_cost_usd=0.0, run_id=None,
            worker_outcome="no_workers", tests_passed=False,
            merged=False, diagnostic="empty backlog",
        )

    monkeypatch.setattr("harness.orchestrator.run_one_cycle",
                        _fake_run_one_cycle)
    outcomes = run_loop(max_cycles=100)
    assert len(outcomes) == 1
    assert counts["n"] == 1, (
        f"loop should stop after first empty-backlog signal; "
        f"ran {counts['n']} cycles"
    )


def test_run_loop_respects_max_cycles(monkeypatch) -> None:
    """max_cycles is a hard cap.  Sentinel: under any `cycle < max_cycles`
    mutation (e.g. `<=`), the loop could over-run."""
    counts = {"n": 0}

    def _fake_run_one_cycle(cycle, dry_run=False, repo_root=None):
        counts["n"] += 1
        return CycleOutcome(
            cycle=cycle, started_at="t", elapsed_s=0,
            todo_id="TASK", composer_engine="mimo",
            composer_cost_usd=0.0, run_id="r1",
            worker_outcome="completed", tests_passed=True,
            merged=True, diagnostic="ok",
        )

    monkeypatch.setattr("harness.orchestrator.run_one_cycle",
                        _fake_run_one_cycle)
    outcomes = run_loop(max_cycles=3)
    assert len(outcomes) == 3, (
        f"loop should run exactly 3 cycles with max_cycles=3; "
        f"ran {counts['n']}"
    )


# ===========================================================================
# Edge: dry_run + no_workers paths
# ===========================================================================


def test_dry_run_skips_integrate(tmp_path: Path) -> None:
    """dry_run=True must not invoke the integrate subprocess even when
    workers are all completed."""
    repo = _setup_run_dir(tmp_path)
    integrate_called = {"n": 0}

    def _safe_run_stub(cmd, **kwargs):
        # Only the composer should fire (rc=0); integrate must NOT fire
        # because dry_run gates it via `not dry_run`.
        # Match on the `coord integrate` subcommand specifically — the
        # tmp_path can contain the substring "integrate" via the test
        # name, so a naive contains-check false-positives the composer.
        if "integrate" in cmd and "coord" in cmd:
            integrate_called["n"] += 1
        return (0, "", "")

    with patch("harness.orchestrator._safe_run", side_effect=_safe_run_stub):
        outcome = run_one_cycle(1, dry_run=True, repo_root=repo)
    assert integrate_called["n"] == 0, (
        f"dry_run=True must not invoke integrate; "
        f"called {integrate_called['n']} times"
    )
    assert outcome.merged is False
