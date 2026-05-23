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
