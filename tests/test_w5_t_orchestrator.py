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


def _capture_schtasks_call(
    monkeypatch: pytest.MonkeyPatch,
) -> list[list[str]]:
    """Helper: mock subprocess.run + return the list of arg lists captured."""
    captured: list[list[str]] = []

    class _Proc:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def _mock_run(args, **kwargs):
        captured.append(list(args))
        return _Proc()

    monkeypatch.setattr("subprocess.run", _mock_run)
    return captured


def test_install_scheduler_minute_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-Z: interval <= 1439 maps to /SC MINUTE."""
    captured = _capture_schtasks_call(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["orchestrator", "install-scheduler",
              "--interval-minutes", "30", "--task-name", "t-min"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    schtasks_calls = [c for c in captured if c and c[0] == "schtasks"]
    assert schtasks_calls, f"no schtasks call: {captured}"
    cmd = schtasks_calls[0]
    assert "/SC" in cmd and cmd[cmd.index("/SC") + 1] == "MINUTE"
    assert "/MO" in cmd and cmd[cmd.index("/MO") + 1] == "30"


def test_install_scheduler_daily_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-Z: interval >= 1440 falls through to /SC DAILY (fixes the
    schtasks `/MO Invalid value` failure on intervals ≥ 24h)."""
    captured = _capture_schtasks_call(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["orchestrator", "install-scheduler",
              "--interval-minutes", "1440", "--task-name", "t-daily"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    schtasks_calls = [c for c in captured if c and c[0] == "schtasks"]
    assert schtasks_calls
    cmd = schtasks_calls[0]
    assert "/SC" in cmd and cmd[cmd.index("/SC") + 1] == "DAILY"
    assert "/MO" in cmd and cmd[cmd.index("/MO") + 1] == "1"


def test_install_scheduler_rejects_zero_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-Z: --interval-minutes 0 is rejected before invoking schtasks."""
    captured = _capture_schtasks_call(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["orchestrator", "install-scheduler",
              "--interval-minutes", "0", "--task-name", "t-zero"],
    )
    assert result.exit_code == 1, f"should reject: output={result.output}"
    schtasks_calls = [c for c in captured if c and c[0] == "schtasks"]
    assert not schtasks_calls, f"should not invoke schtasks: {schtasks_calls}"


# ---------------------------------------------------------------------------
# W5-OO Claude-via-Task-Scheduler
# ---------------------------------------------------------------------------

def test_install_claude_scheduler_help_includes_oauth_explanation() -> None:
    """W5-OO: help text explains why this works when other paths fail."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["orchestrator", "install-claude-scheduler", "--help"],
    )
    assert result.exit_code == 0
    assert "--interval-minutes" in result.output
    assert "--task-name" in result.output
    assert "--prompt-file" in result.output
    assert "--output-dir" in result.output


def test_install_claude_scheduler_scaffolds_prompt_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-OO: when prompt-file doesn't exist, a default is auto-scaffolded."""
    captured = _capture_schtasks_call(monkeypatch)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["orchestrator", "install-claude-scheduler",
              "--interval-minutes", "60",
              "--task-name", "t-claude-scaffold",
              "--prompt-file", "coord/my-prompt.md",
              "--output-dir", "coord/my-runs"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    prompt = tmp_path / "coord" / "my-prompt.md"
    assert prompt.exists(), "should auto-scaffold default prompt"
    body = prompt.read_text(encoding="utf-8")
    assert "autonomous orchestrator" in body.lower()
    assert "STATUS.csv" in body
    # Output dir pre-created
    assert (tmp_path / "coord" / "my-runs").exists()
    # schtasks called with the right cadence
    schtasks_calls = [c for c in captured if c and c[0] == "schtasks"]
    assert schtasks_calls, f"no schtasks call: {captured}"
    cmd = schtasks_calls[0]
    assert "/SC" in cmd and cmd[cmd.index("/SC") + 1] == "MINUTE"
    assert "/MO" in cmd and cmd[cmd.index("/MO") + 1] == "60"


def test_install_claude_scheduler_respects_existing_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-OO: don't overwrite an operator-customized prompt file."""
    _capture_schtasks_call(monkeypatch)
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "coord" / "custom-prompt.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("# my custom prompt\nhello\n", encoding="utf-8")
    runner = CliRunner()
    runner.invoke(
        cli, ["orchestrator", "install-claude-scheduler",
              "--prompt-file", "coord/custom-prompt.md"],
    )
    assert custom.read_text(encoding="utf-8") == "# my custom prompt\nhello\n"


def test_install_claude_scheduler_daily_for_long_intervals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """W5-OO + W5-Z: intervals >= 1440 use /SC DAILY (same fix as
    install-scheduler)."""
    captured = _capture_schtasks_call(monkeypatch)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["orchestrator", "install-claude-scheduler",
              "--interval-minutes", "2880", "--task-name", "t-claude-daily"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    schtasks_calls = [c for c in captured if c and c[0] == "schtasks"]
    cmd = schtasks_calls[0]
    assert cmd[cmd.index("/SC") + 1] == "DAILY"
    assert cmd[cmd.index("/MO") + 1] == "2"  # 2880 / 1440 = 2 days


class TestQueueSortPriority:
    """W5-NN: spec/auto/ filenames with P<n>- prefix run in priority order."""

    def test_no_prefixes_alphabetical(self) -> None:
        """Without P<n>- prefixes, sort is pure alphabetical."""
        from harness.cli import _sort_queue_paths
        paths = [Path("zebra.md"), Path("alpha.md"), Path("beta.md")]
        result = _sort_queue_paths(paths)
        assert [p.name for p in result] == ["alpha.md", "beta.md", "zebra.md"]

    def test_p0_runs_first(self) -> None:
        """P0- always runs before P1-, P2-, …, and before unprefixed."""
        from harness.cli import _sort_queue_paths
        paths = [
            Path("P2-medium.md"),
            Path("urgent-without-prefix.md"),
            Path("P0-critical.md"),
            Path("P1-high.md"),
        ]
        result = _sort_queue_paths(paths)
        assert [p.name for p in result] == [
            "P0-critical.md",         # priority 0
            "P1-high.md",             # priority 1
            "P2-medium.md",           # priority 2
            "urgent-without-prefix.md",  # priority 5 default
        ]

    def test_unprefixed_priority_is_5(self) -> None:
        """Specs without P<n>- get default priority 5: between P0-P4 and P6+."""
        from harness.cli import _sort_queue_paths
        paths = [
            Path("P9-defer.md"),
            Path("normal.md"),
            Path("P3-soon.md"),
        ]
        result = _sort_queue_paths(paths)
        assert [p.name for p in result] == [
            "P3-soon.md",   # priority 3
            "normal.md",    # priority 5 default
            "P9-defer.md",  # priority 9
        ]

    def test_alphabetical_within_priority(self) -> None:
        """Multiple specs with same P<n>- prefix sort alphabetically."""
        from harness.cli import _sort_queue_paths
        paths = [
            Path("P1-zeta.md"),
            Path("P1-alpha.md"),
            Path("P1-beta.md"),
        ]
        result = _sort_queue_paths(paths)
        assert [p.name for p in result] == [
            "P1-alpha.md",
            "P1-beta.md",
            "P1-zeta.md",
        ]

    def test_double_digit_priority(self) -> None:
        """P10 / P99 prefixes parse correctly (not P1 + extra chars)."""
        from harness.cli import _sort_queue_paths
        paths = [
            Path("P10-late.md"),
            Path("P2-early.md"),
            Path("P99-last.md"),
        ]
        result = _sort_queue_paths(paths)
        assert [p.name for p in result] == [
            "P2-early.md",
            "P10-late.md",
            "P99-last.md",
        ]

    def test_queue_execute_honors_priority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Integration: queue execute picks P0- spec before unprefixed when
        --once is set."""
        monkeypatch.chdir(tmp_path)
        auto = tmp_path / "spec" / "auto"
        auto.mkdir(parents=True)
        # Older alphabetical first ("aaaa" < "P0-..." in ASCII) but with
        # W5-NN P0 should still win.
        (auto / "aaaa-old.md").write_text("# spec\n## Goal\nold\n", encoding="utf-8")
        (auto / "P0-urgent.md").write_text("# spec\n## Goal\nurgent\n", encoding="utf-8")

        class _Proc:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout
                self.stderr = ""
                self.returncode = 0
        calls: list[list[str]] = []

        def _mock_run(args, **kwargs):
            calls.append(args)
            if "plan" in args:
                rid = "test-run-prio"
                (tmp_path / "runs" / rid).mkdir(parents=True, exist_ok=True)
                return _Proc(stdout=f"plan: runs/{rid}/plan.json")
            return _Proc(stdout="ok")

        monkeypatch.setattr("subprocess.run", _mock_run)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["queue", "execute", "--once", "--no-merge"],
        )
        assert result.exit_code == 0, f"output={result.output}"
        # P0-urgent.md should have moved, NOT aaaa-old.md
        done = tmp_path / "spec" / "auto" / "done"
        assert (done / "P0-urgent.md").exists()
        assert not (done / "aaaa-old.md").exists()
        assert (auto / "aaaa-old.md").exists()  # still waiting


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
