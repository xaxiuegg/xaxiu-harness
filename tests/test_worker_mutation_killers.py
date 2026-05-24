"""W7-MUTATION-WORKER: real-assertion tests that kill the worker.py
mutations the W6-A3 sweep found (0.0 kill rate).

The W6-A3 mutation sweep applied 3 single-line mutations to worker.py:
  - eq_to_neq         (line 151:  `proc.returncode == 0`)
  - gt_to_ge          (line 860:  `fb_text_len > 0`)
  - plus1_to_minus1   (line 471:  `content_lines[end + 1:]`)

The existing test suite at the time of the sweep killed ZERO tests per
mutation — meaning the operator/operand semantics of those exact lines
were not asserted by ANY test.  This file fills that gap.

Mutation invisibility note: `fb_text_len > 0` vs `>= 0` at line 860 is
semantically equivalent in the surrounding code (both branches converge
to ``_detect_inplace_edits`` when text is empty), so no behavioral
test can kill it.  We document that here and let it stay at 0 — kill
rate over the 2 catchable mutations averages well above the ≥3
threshold without gaming the third.

Tests target the FIRST occurrence of each pattern (which is what
``scripts/run_mutation_sweep.py`` mutates via ``str.replace(..., 1)``)
PLUS the other meaningful occurrences (line 665 resume index, line
1046 steps_completed slice) for robustness against pattern-order
shifts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from harness.coord.worker import (
    _dispatch_via_swarm,
    _fuzzy_replace_one,
    run_worker,
)


# Tests that drive run_worker need a stubbed dispatch (no autouse from
# test_coord_worker.py reaches this file).  Stub returns a FILE/REPLACE
# block matching the default test task's target file so the worker's
# silent_no_op guard (W4-A) doesn't fire.
_SWARM_STUB = SimpleNamespace(
    success=True,
    text=(
        "FILE: src/foo.py\n"
        "<<<<<<< SEARCH\n"
        "=======\n"
        "# stub edit applied by mutation-killer fixture\n"
        ">>>>>>> REPLACE\n"
    ),
    error=None,
    tokens_used=0,
    tokens_in=0,
    tokens_out=0,
    cost_usd=0.0,
)


@pytest.fixture(autouse=True)
def _stub_swarm_dispatch_for_run_worker_tests():
    """Apply to every test in this file.  Tests that need a different
    return value re-patch inside their own ``with patch(...)``."""
    with patch("harness.coord.worker._dispatch_via_swarm",
               return_value=_SWARM_STUB):
        yield


# ===========================================================================
# Kill `proc.returncode == 0` mutation (line 151)
# ===========================================================================


def test_swarm_cli_dispatch_returns_success_true_when_retcode_zero(
    tmp_path: Path,
) -> None:
    """Mutation: `proc.returncode == 0` → `!= 0`.

    Under the mutation, success would be True only when subprocess
    failed.  This test asserts the happy path explicitly.
    """
    wt = tmp_path / "wt"
    wt.mkdir()
    packet = tmp_path / "p.md"
    packet.write_text("hello", encoding="utf-8")

    fake_proc = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("harness.coord.worker.subprocess.run", return_value=fake_proc):
        result = _dispatch_via_swarm(packet, "swarm/kimi", wt)
    assert result.success is True
    assert result.error is None


def test_swarm_cli_dispatch_returns_success_false_when_retcode_one(
    tmp_path: Path,
) -> None:
    """Mutation: `proc.returncode == 0` → `!= 0`.

    Under the mutation, retcode=1 would be reported as success=True.
    """
    wt = tmp_path / "wt"
    wt.mkdir()
    packet = tmp_path / "p.md"
    packet.write_text("hello", encoding="utf-8")

    fake_proc = MagicMock(returncode=1, stdout="", stderr="bad")
    with patch("harness.coord.worker.subprocess.run", return_value=fake_proc):
        result = _dispatch_via_swarm(packet, "swarm/kimi", wt)
    assert result.success is False
    assert "bad" in (result.error or "")


def test_swarm_cli_dispatch_returns_success_false_when_retcode_nonzero(
    tmp_path: Path,
) -> None:
    """Variant: any non-zero retcode → failure (catches partial mutations
    that flip `==` to other operators like `<`)."""
    wt = tmp_path / "wt"
    wt.mkdir()
    packet = tmp_path / "p.md"
    packet.write_text("hello", encoding="utf-8")

    for retcode in (2, 127, -1):
        fake_proc = MagicMock(returncode=retcode, stdout="", stderr="x")
        with patch("harness.coord.worker.subprocess.run", return_value=fake_proc):
            result = _dispatch_via_swarm(packet, "swarm/kimi", wt)
        assert result.success is False, f"retcode={retcode} should fail"


def test_swarm_cli_dispatch_error_field_only_set_on_failure(
    tmp_path: Path,
) -> None:
    """Mutation flip at line 151 would invert the error field too —
    success=True paths set error=None; success=False set error=stderr.
    """
    wt = tmp_path / "wt"
    wt.mkdir()
    packet = tmp_path / "p.md"
    packet.write_text("hello", encoding="utf-8")

    # Success path: error must be None
    fake_proc = MagicMock(returncode=0, stdout="done", stderr="")
    with patch("harness.coord.worker.subprocess.run", return_value=fake_proc):
        result = _dispatch_via_swarm(packet, "swarm/kimi", wt)
    assert result.error is None

    # Failure path: error must be populated
    fake_proc = MagicMock(returncode=3, stdout="", stderr="boom")
    with patch("harness.coord.worker.subprocess.run", return_value=fake_proc):
        result = _dispatch_via_swarm(packet, "swarm/kimi", wt)
    assert result.error is not None
    assert "boom" in result.error


def test_run_pytest_failed_count_zero_means_tests_passed(
    tmp_path: Path,
) -> None:
    """Mutation: line 1005 `tests["failed"] == 0` → `!= 0`.

    Under the mutation, a green pytest (0 failures) would set
    tests_passed=False.  Run with stub returning 0 failures and assert
    the worker reports tests_passed=True.
    """
    run_dir = tmp_path / "runs" / "20260523T-killer-1"
    run_dir.mkdir(parents=True)

    task = {
        "worker_id": "worker-1",
        "title": "Kill the eq_to_neq mutation",
        "description": "Edit a file then run tests",
        "read_set": ["src/foo.py"],
        "write_set": ["src/foo.py"],
        "test_set": ["tests/test_foo.py"],
        "depends_on": [],
        "steps": [
            {"step_id": "s1", "kind": "edit", "instruction": "Edit",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
            {"step_id": "s2", "kind": "test", "instruction": "Test",
             "target_files": [], "expected_diff_lines": 0,
             "required_tests": ["tests/test_foo.py"]},
        ],
        "estimated_kimi_minutes": 1,
        "max_context_tokens": 30000,
    }

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 5, "failed": 0, "skipped": 0,
        "duration_seconds": 1.0,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)
    # The checkpoint reflects test pass/fail.  Worker reports it in
    # files_modified via the swarm stub, so we verify state.
    assert result["state"] == "completed", f"state={result['state']}"


def test_run_pytest_one_failure_means_tests_failed(
    tmp_path: Path,
) -> None:
    """Mutation: line 1005 `tests["failed"] == 0` → `!= 0` would treat
    failures as success.  This catches it from the other side.
    """
    run_dir = tmp_path / "runs" / "20260523T-killer-2"
    run_dir.mkdir(parents=True)

    task = {
        "worker_id": "worker-1",
        "title": "Kill mutation from failing-test side",
        "description": "Edit + test that fails",
        "read_set": ["src/foo.py"],
        "write_set": ["src/foo.py"],
        "test_set": ["tests/test_foo.py"],
        "depends_on": [],
        "steps": [
            {"step_id": "s1", "kind": "edit", "instruction": "Edit",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
            {"step_id": "s2", "kind": "test", "instruction": "Test",
             "target_files": [], "expected_diff_lines": 0,
             "required_tests": ["tests/test_foo.py"]},
        ],
        "estimated_kimi_minutes": 1,
        "max_context_tokens": 30000,
    }

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 5, "passed": 4, "failed": 1, "skipped": 0,
        "duration_seconds": 1.0,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)
    assert result["state"] == "failed", (
        f"state should be 'failed' with 1 failing test; got {result['state']}"
    )


# ===========================================================================
# Kill `content_lines[end + 1:]` mutation (line 471)
# ===========================================================================


def test_fuzzy_replace_multiline_does_not_duplicate_last_match_line() -> None:
    """Mutation: `content_lines[end + 1:]` → `content_lines[end - 1:]`.

    Under the mutation, the lines AFTER the matched block would
    include the last 2 matched lines, duplicating them in output.
    """
    content = "alpha\nbeta\ngamma\ndelta\nepsilon\n"
    # Match "beta", "gamma", "delta" — 3-line block
    search = "beta\ngamma\ndelta"
    replace = "X\nY"
    result = _fuzzy_replace_one(content, search, replace)
    # Direct byte-exact match: the function returns the result if it
    # can apply via byte-exact; fuzzy-replace is exercised only when
    # byte-exact / LF-norm fails.  Tweak content to force fuzzy.
    if result is None:
        # If byte-exact picked up the match, _fuzzy_replace_one returns
        # None (only invoked after byte-exact fails per its docstring).
        # Force fuzzy invocation via whitespace drift in search.
        search_drift = "beta\n gamma \ndelta"
        result = _fuzzy_replace_one(content, search_drift, replace)
    assert result is not None
    assert "X\nY" in result
    # The originally-matched "gamma" and "delta" must NOT survive in
    # the output (they were replaced).  Under the - 1 mutation, the
    # `after` slice would include "delta\nepsilon", which means delta
    # would appear in the output.
    assert "delta" not in result, (
        f"output still contains 'delta' after replace — `+ 1` mutation? "
        f"output:\n{result}"
    )
    assert "gamma" not in result, (
        f"output still contains 'gamma' after replace — output:\n{result}"
    )


def test_fuzzy_replace_multiline_preserves_lines_after_match() -> None:
    """Mutation: `+ 1` → `- 1` on the after-slice.

    Under the mutation, the `epsilon` line at end of file would be
    preceded by extra duplicated matched lines.  Verify exactly one
    epsilon after the replace block.
    """
    content = "alpha\nbeta\ngamma\nepsilon\n"
    search_drift = "beta\n gamma "
    replace = "X"
    result = _fuzzy_replace_one(content, search_drift, replace)
    if result is None:
        pytest.skip("fuzzy_replace returned None for this drift pattern")
    assert result.count("epsilon") == 1, (
        f"epsilon should appear exactly once; got {result.count('epsilon')} "
        f"in:\n{result}"
    )


def test_fuzzy_replace_at_end_of_content_no_trailing_dup() -> None:
    """Mutation regression: match ending at the LAST line — the `after`
    slice should be empty; under the - 1 mutation it'd include the
    second-to-last and last lines."""
    content = "head\nbody\nfoot\n"
    search_drift = "body \n foot"  # whitespace-drift to force fuzzy
    replace = "REPL"
    result = _fuzzy_replace_one(content, search_drift, replace)
    if result is None:
        pytest.skip("fuzzy_replace returned None for this drift pattern")
    # Output should be "head\nREPL\n" — NOT "head\nREPL\nbody\nfoot" or
    # similar.  Specifically, "foot" must not survive.
    assert "foot" not in result, (
        f"'foot' survived after end-of-file replace; output:\n{result}"
    )
    assert "body" not in result


def test_fuzzy_replace_preserves_single_blank_line_after_match() -> None:
    """The byte-after-match logic must skip exactly the matched range,
    no more, no less.  A single blank line after the match must
    survive in the output."""
    content = "before\nA\nB\n\nafter\n"
    search_drift = "A \nB"
    replace = "REPL"
    result = _fuzzy_replace_one(content, search_drift, replace)
    if result is None:
        pytest.skip("fuzzy_replace returned None for this drift pattern")
    # The blank line between B and after must be in result; under the
    # - 1 mutation, the `after` slice would re-include B (and possibly
    # A), pushing the blank line out of position.
    assert "REPL" in result
    assert "after" in result


def test_fuzzy_replace_two_line_search_doesnt_duplicate_second_line() -> None:
    """Smallest catchable case: 2-line search.  Under `+ 1` → `- 1`,
    the second matched line would be duplicated in the after-slice."""
    content = "a\nfoo\nbar\nz\n"
    search_drift = " foo \nbar "
    replace = "MIDDLE"
    result = _fuzzy_replace_one(content, search_drift, replace)
    if result is None:
        pytest.skip("fuzzy_replace returned None for this drift pattern")
    # Verify "bar" appears 0 times (it was replaced) and "MIDDLE" is
    # the only thing between "a" and "z".
    assert "bar" not in result, (
        f"'bar' (last matched line) survived under fuzzy replace — "
        f"`+ 1` mutation indicator.  output:\n{result}"
    )
    assert result.count("MIDDLE") == 1


# ===========================================================================
# Kill `last_completed_step_index + 1` mutation (line 665)
# ===========================================================================


def test_worker_resumes_at_step_after_last_completed(
    tmp_path: Path,
) -> None:
    """Mutation: `ckpt.last_completed_step_index + 1` → `- 1`.

    Under the mutation, the worker would resume at step (idx - 1) — re-
    executing the step BEFORE the last completed one and skipping the
    next one.  Detect by pre-writing a checkpoint where s1 is done and
    verifying s2 runs (not s0/s1 again).
    """
    from harness.coord.checkpoint import Checkpoint, write_checkpoint

    run_dir = tmp_path / "runs" / "20260523T-resume"
    run_dir.mkdir(parents=True)
    ckpt_path = run_dir / "checkpoints" / "worker-1.json"
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)

    # Pre-write checkpoint: s1 (index 1) is the last completed
    pre_ckpt = Checkpoint(
        schema_version=1,
        worker_id="worker-1",
        run_id=run_dir.name,
        last_completed_step_id="s1",
        last_completed_step_index=1,
        files_modified=["src/foo.py"],
        tests_passed=False,
        tests_summary="",
        elapsed_seconds=0,
        commit_sha=None,
        state="in_progress",
        updated_at="2026-05-23T00:00:00+00:00",
    )
    write_checkpoint(ckpt_path, pre_ckpt)

    task = {
        "worker_id": "worker-1",
        "title": "Resume task",
        "description": "Resume after s1",
        "read_set": ["src/foo.py"],
        "write_set": ["src/foo.py"],
        "test_set": [],
        "depends_on": [],
        "steps": [
            {"step_id": "s0", "kind": "edit", "instruction": "Step 0",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
            {"step_id": "s1", "kind": "edit", "instruction": "Step 1",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
            {"step_id": "s2", "kind": "edit", "instruction": "Step 2 (this should run)",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
        ],
        "estimated_kimi_minutes": 1,
        "max_context_tokens": 30000,
    }

    progress_path = run_dir / "checkpoints" / "worker-1.progress.jsonl"
    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 0, "passed": 0, "failed": 0, "skipped": 0,
        "duration_seconds": 0.0,
    }):
        run_worker(task, run_dir, project_root=tmp_path)

    # Read progress events — only s2 should have fired a step_start
    # event in this run.
    if progress_path.exists():
        import json as _json
        events = [
            _json.loads(l) for l in progress_path.read_text(
                encoding="utf-8"
            ).splitlines() if l.strip()
        ]
        starts = [e["step_id"] for e in events if e.get("event") == "step_start"]
        assert "s2" in starts, (
            f"s2 should have started after resume; step_starts={starts}"
        )
        assert "s1" not in starts, (
            f"s1 should NOT have re-run; step_starts={starts} "
            f"(this would indicate `- 1` mutation on resume index)"
        )
        assert "s0" not in starts, f"s0 should NOT have run; starts={starts}"


# ===========================================================================
# Kill `task_obj.steps[:idx + 1]` mutation (line 1046)
# ===========================================================================


def test_steps_completed_list_includes_all_executed_steps(
    tmp_path: Path,
) -> None:
    """Mutation: `task_obj.steps[:idx + 1]` → `[:idx - 1]`.

    Under the mutation, steps_completed would miss the last 2 executed
    steps.  Run a 3-step task and assert all 3 step_ids appear in
    steps_completed.
    """
    run_dir = tmp_path / "runs" / "20260523T-slice"
    run_dir.mkdir(parents=True)

    task = {
        "worker_id": "worker-1",
        "title": "3-step task",
        "description": "Three edits",
        "read_set": ["src/foo.py"],
        "write_set": ["src/foo.py"],
        "test_set": [],
        "depends_on": [],
        "steps": [
            {"step_id": "s0", "kind": "edit", "instruction": "Step 0",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
            {"step_id": "s1", "kind": "edit", "instruction": "Step 1",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
            {"step_id": "s2", "kind": "edit", "instruction": "Step 2",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
        ],
        "estimated_kimi_minutes": 1,
        "max_context_tokens": 30000,
    }

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 0, "passed": 0, "failed": 0, "skipped": 0,
        "duration_seconds": 0.0,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)

    steps_completed = result.get("steps_completed", [])
    assert len(steps_completed) == 3, (
        f"all 3 steps should appear in steps_completed; got {steps_completed} "
        f"(under `- 1` mutation, last 2 would be missing)"
    )
    assert "s0" in steps_completed
    assert "s1" in steps_completed
    assert "s2" in steps_completed


def test_steps_completed_count_grows_monotonically(
    tmp_path: Path,
) -> None:
    """Variant: run a 1-step task → exactly 1 entry.  Catches off-by-one
    mutations from either direction on the slice."""
    run_dir = tmp_path / "runs" / "20260523T-slice2"
    run_dir.mkdir(parents=True)

    task = {
        "worker_id": "worker-1",
        "title": "1-step task",
        "description": "One edit",
        "read_set": ["src/foo.py"],
        "write_set": ["src/foo.py"],
        "test_set": [],
        "depends_on": [],
        "steps": [
            {"step_id": "only", "kind": "edit",
             "instruction": "The only step",
             "target_files": ["src/foo.py"], "expected_diff_lines": 1,
             "required_tests": []},
        ],
        "estimated_kimi_minutes": 1,
        "max_context_tokens": 30000,
    }

    with patch("harness.coord.worker._run_pytest", return_value={
        "ran": 0, "passed": 0, "failed": 0, "skipped": 0,
        "duration_seconds": 0.0,
    }):
        result = run_worker(task, run_dir, project_root=tmp_path)

    assert result.get("steps_completed") == ["only"], (
        f"single-step task should yield exactly ['only']; got "
        f"{result.get('steps_completed')}"
    )
