"""W5-T orchestrator unit tests.

Covers the merge-policy logic + CLI surface.  Live engine dispatch
covered by separate integration tests via real pilots.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_orchestrator_start_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["orchestrator", "start", "--help"])
    assert result.exit_code == 0
    assert "--once" in result.output
    assert "--max-cycles" in result.output
    assert "--interval-seconds" in result.output
    assert "--dry-run" in result.output


def test_orchestrator_install_scheduler_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["orchestrator", "install-scheduler", "--help"])
    assert result.exit_code == 0
    assert "--interval-minutes" in result.output
    assert "--task-name" in result.output


def test_orchestrator_group_help_mentions_path_alpha() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["orchestrator", "--help"])
    assert result.exit_code == 0
    # Path α mention (encoded as alpha sometimes)
    assert "autonomous" in result.output.lower()


# ---------------------------------------------------------------------------
# Queue CLI
# ---------------------------------------------------------------------------

def test_queue_list_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["queue", "list"])
    assert result.exit_code == 0
    assert "does not exist" in result.output or "pending: 0" in result.output


def test_queue_list_with_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "spec" / "auto").mkdir(parents=True)
    (tmp_path / "spec" / "auto" / "alpha.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "spec" / "auto" / "beta.md").write_text("# B\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["queue", "list"])
    assert result.exit_code == 0
    assert "pending: 2" in result.output
    assert "alpha.md" in result.output
    assert "beta.md" in result.output


def test_queue_execute_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "spec" / "auto").mkdir(parents=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["queue", "execute"])
    assert result.exit_code == 0
    assert "Queue empty" in result.output


def test_queue_execute_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["queue", "execute", "--help"])
    assert result.exit_code == 0
    assert "--once" in result.output
    assert "--max" in result.output
    assert "--no-merge" in result.output


def test_queue_execute_processes_pending_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W5-U regression guard: exercise the subprocess.run codepath with
    a real spec in the queue.  This caught a NameError where subprocess
    was referenced inside queue_execute_cmd but not imported at module
    top (the bug was invisible to test_queue_execute_empty because that
    test short-circuits before reaching subprocess.run)."""
    import subprocess as _subprocess  # noqa: F401  — proves import wiring

    monkeypatch.chdir(tmp_path)
    auto = tmp_path / "spec" / "auto"
    auto.mkdir(parents=True)
    spec = auto / "test-spec.md"
    spec.write_text("# SPEC-ID: test\n\n## Goal\nDo a thing.\n", encoding="utf-8")

    # Mock subprocess.run so we don't actually fork harness subprocesses.
    class _MockProc:
        def __init__(self, stdout: str, returncode: int = 0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    calls: list[list[str]] = []

    def _mock_run(args, **kwargs):
        calls.append(args)
        # Simulate `coord plan` output that the parser can extract a
        # run-id from.
        if "plan" in args:
            rid = "test-run-123"
            (tmp_path / "runs" / rid).mkdir(parents=True, exist_ok=True)
            return _MockProc(stdout=f"plan: runs/{rid}/plan.json")
        # `coord run` or `coord integrate` — return success.
        return _MockProc(stdout="ok")

    monkeypatch.setattr("subprocess.run", _mock_run)

    runner = CliRunner()
    result = runner.invoke(cli, ["queue", "execute", "--once", "--no-merge"])
    # The CliRunner SystemExit is captured; exit_code reflects sys.exit(0).
    assert result.exit_code == 0, f"output={result.output}\nexception={result.exception}"
    # Spec should have been moved to spec/auto/done/
    assert not spec.exists(), "Spec should have moved to done/"
    assert (auto / "done" / "test-spec.md").exists()
    # At least the plan call should have been made.
    assert any("plan" in c for c in calls), f"calls={calls}"
    # W5-AA: default planner engine is kimi-api, not claude.
    plan_calls = [c for c in calls if "plan" in c]
    assert any("kimi-api" in c for c in plan_calls), \
        f"plan calls should default to kimi-api: {plan_calls}"


def test_queue_execute_planner_engine_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W5-AA: --planner-engine overrides the default kimi-api."""
    monkeypatch.chdir(tmp_path)
    auto = tmp_path / "spec" / "auto"
    auto.mkdir(parents=True)
    spec = auto / "p.md"
    spec.write_text("# SPEC-ID: p\n\n## Goal\nDo.\n", encoding="utf-8")

    class _MockProc:
        def __init__(self, stdout: str, returncode: int = 0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    calls: list[list[str]] = []

    def _mock_run(args, **kwargs):
        calls.append(args)
        if "plan" in args:
            rid = "test-run-456"
            (tmp_path / "runs" / rid).mkdir(parents=True, exist_ok=True)
            return _MockProc(stdout=f"plan: runs/{rid}/plan.json")
        return _MockProc(stdout="ok")

    monkeypatch.setattr("subprocess.run", _mock_run)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["queue", "execute", "--once", "--no-merge",
              "--planner-engine", "deepseek"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    plan_calls = [c for c in calls if "plan" in c]
    assert any("deepseek" in c for c in plan_calls), \
        f"--planner-engine deepseek should land in plan call: {plan_calls}"
    assert not any("kimi-api" in c for c in plan_calls), \
        f"override should suppress default: {plan_calls}"


# ---------------------------------------------------------------------------
# Orchestrator module — dry-run path
# ---------------------------------------------------------------------------

def test_run_one_cycle_dry_run_smoke(tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """run_one_cycle in dry-run should not crash + return CycleOutcome
    with expected shape."""
    from harness.orchestrator import run_one_cycle, CycleOutcome

    # Set up minimal repo skeleton
    monkeypatch.chdir(tmp_path)
    (tmp_path / "coord").mkdir()
    (tmp_path / "coord" / "coverage").mkdir()
    (tmp_path / "scripts").mkdir()
    # Stub the orchestrator_c_hybrid.py with a script that just exits
    # without producing any cycle report.
    (tmp_path / "scripts" / "orchestrator_c_hybrid.py").write_text(
        "import sys\nsys.exit(1)\n", encoding="utf-8"
    )

    outcome = run_one_cycle(1, dry_run=True, repo_root=tmp_path)
    assert isinstance(outcome, CycleOutcome)
    # No cycle report exists → worker_outcome should be no_workers
    assert outcome.worker_outcome == "no_workers"
    assert outcome.tests_passed is False
    assert outcome.merged is False
    assert outcome.cycle == 1
