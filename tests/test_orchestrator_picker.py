"""Tests for W5-SS: harness start orchestrator picker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.orchestrator_picker import (
    ConnectionStatus,
    ORCHESTRATORS,
    Orchestrator,
    by_key,
    render_picker,
)


# ---------------------------------------------------------------------------
# orchestrator metadata
# ---------------------------------------------------------------------------

def test_four_orchestrators_registered() -> None:
    """W5-SS contract: exactly 4 selectable orchestrators."""
    keys = [o.key for o in ORCHESTRATORS]
    assert set(keys) == {"claude", "mimo", "deepseek", "kimi"}


def test_mimo_is_default_first() -> None:
    """W5-SS UX: MiMo is option [1] (brainstorm-recommended primary)."""
    assert ORCHESTRATORS[0].key == "mimo"


def test_by_key_returns_orchestrator_or_none() -> None:
    assert by_key("mimo") is not None
    assert by_key("mimo").key == "mimo"
    assert by_key("nonexistent") is None


# ---------------------------------------------------------------------------
# probe()
# ---------------------------------------------------------------------------

def test_probe_mimo_ready_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIMO_API_KEY", "tp-x")
    o = by_key("mimo")
    assert o.probe() == ConnectionStatus.READY


def test_probe_mimo_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    o = by_key("mimo")
    assert o.probe() == ConnectionStatus.MISSING_KEY


def test_probe_kimi_accepts_either_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kimi accepts KIMI_API_KEY_1 OR legacy KIMI_API_KEY."""
    monkeypatch.delenv("KIMI_API_KEY_1", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    o = by_key("kimi")
    assert o.probe() == ConnectionStatus.MISSING_KEY
    monkeypatch.setenv("KIMI_API_KEY", "tp-legacy")
    assert o.probe() == ConnectionStatus.READY


def test_probe_claude_blocked_inside_claude_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude can't run inside another Claude Code session (anti-recursion)."""
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "12345")
    o = by_key("claude")
    assert o.probe() == ConnectionStatus.BLOCKED


def test_probe_claude_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `claude` binary is missing, status is NOT_INSTALLED."""
    monkeypatch.delenv("CLAUDE_CODE_SSE_PORT", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    o = by_key("claude")
    assert o.probe() == ConnectionStatus.NOT_INSTALLED


# ---------------------------------------------------------------------------
# render_picker()
# ---------------------------------------------------------------------------

def test_render_picker_includes_all_4_with_badges() -> None:
    text = render_picker(probe_fn=lambda o: ConnectionStatus.READY)
    for o in ORCHESTRATORS:
        assert o.label in text
        assert o.best_for in text
        assert o.cost in text
    assert text.count("✓ ready") == 4


def test_render_picker_shows_blocked_status_for_claude() -> None:
    def _probe(o: Orchestrator) -> ConnectionStatus:
        return ConnectionStatus.BLOCKED if o.key == "claude" else ConnectionStatus.READY
    text = render_picker(probe_fn=_probe)
    assert "blocked" in text.lower()
    assert "running inside Claude Code session" in text


def test_render_picker_shows_missing_key_with_env_name() -> None:
    def _probe(o: Orchestrator) -> ConnectionStatus:
        return ConnectionStatus.MISSING_KEY if o.key == "deepseek" else ConnectionStatus.READY
    text = render_picker(probe_fn=_probe)
    assert "DEEPSEEK_API_KEY not set" in text


# ---------------------------------------------------------------------------
# harness start CLI verb
# ---------------------------------------------------------------------------

def test_start_list_flag_prints_picker_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--list emits the picker text, exits 0, doesn't prompt or persist."""
    monkeypatch.setenv("MIMO_API_KEY", "x")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("KIMI_API_KEY", "x")
    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--list"])
    assert result.exit_code == 0
    assert "Pick your orchestrator:" in result.output
    assert "MiMo Pro v2.5" in result.output


def test_start_scripted_invocation_persists_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--orchestrator + --mode skips prompts and persists choice."""
    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "mimo", "--mode", "interactive"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    assert "Orchestrator: MiMo Pro v2.5" in result.output
    assert "Mode:         interactive" in result.output
    # State persisted
    state = json.loads(
        (tmp_path / "coord" / "dev_loop" / "state.json").read_text(encoding="utf-8")
    )
    assert state["active_orchestrator"] == "mimo"
    assert state["active_mode"] == "interactive"
    assert "orchestrator_chosen_at" in state


def test_start_blocked_claude_exits_2_with_helpful_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Picking Claude inside a Claude Code session → exit 2 + how-to-fix."""
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "12345")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "claude", "--mode", "interactive"],
    )
    assert result.exit_code == 2, f"output={result.output}"
    assert "BLOCKED" in result.output
    assert "install-claude-scheduler" in result.output


def test_start_missing_key_exits_2_with_env_var_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Picking an orchestrator without its API key → exit 2 naming the var."""
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "mimo", "--mode", "interactive"],
    )
    assert result.exit_code == 2, f"output={result.output}"
    assert "MIMO_API_KEY" in result.output


def test_start_autonomous_mode_attempts_scheduler_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--mode autonomous invokes orchestrator install-scheduler."""
    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []

    class _Proc:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def _mock_run(args, **kwargs):
        calls.append(list(args))
        return _Proc()

    monkeypatch.setattr("subprocess.run", _mock_run)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "mimo", "--mode", "autonomous",
              "--interval-minutes", "45", "--skip-preflight"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    # install-scheduler subprocess called
    scheduler_calls = [
        c for c in calls
        if any("orchestrator" in str(a) for a in c)
        and any("install-scheduler" in str(a) for a in c)
    ]
    assert scheduler_calls, f"no install-scheduler call: {calls}"
    # Cadence threaded through
    assert any("45" in str(a) for c in scheduler_calls for a in c)


def test_start_claude_autonomous_uses_install_claude_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--orchestrator claude --mode autonomous → install-claude-scheduler
    (NOT regular install-scheduler), since Claude needs the OAuth path."""
    # Run from a clean process context (not inside Claude Code) and pretend
    # `claude` is on PATH.
    monkeypatch.delenv("CLAUDE_CODE_SSE_PORT", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []

    class _Proc:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    monkeypatch.setattr("subprocess.run",
                        lambda args, **kw: (calls.append(list(args)), _Proc())[1])
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "claude", "--mode", "autonomous",
              "--skip-preflight"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    assert any(
        "install-claude-scheduler" in str(a)
        for c in calls for a in c
    ), f"should use install-claude-scheduler: {calls}"


# ---------------------------------------------------------------------------
# W6-B3: preflight gate
# ---------------------------------------------------------------------------


def test_start_autonomous_blocked_by_preflight_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Autonomous mode without --skip-preflight refuses to start if
    preflight surfaces a fail-severity check."""
    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    monkeypatch.chdir(tmp_path)
    from harness.preflight import PreflightCheck

    def _fake_run_all():
        return [
            PreflightCheck(name="git_clean", severity="fail",
                           message="dirty tree",
                           fix="commit your work"),
        ]

    monkeypatch.setattr("harness.preflight.run_all", _fake_run_all)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "mimo", "--mode", "autonomous"],
    )
    assert result.exit_code == 4, f"output={result.output}"
    assert "Preflight FAILED" in result.output
    assert "git_clean" in result.output
    assert "commit your work" in result.output


def test_start_autonomous_warns_on_preflight_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Autonomous mode with warn-severity preflight prints warning but
    proceeds to scheduler install."""
    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    monkeypatch.chdir(tmp_path)
    from harness.preflight import PreflightCheck

    def _fake_run_all():
        return [
            PreflightCheck(name="status_csv", severity="warn",
                           message="stale: 30h ago"),
        ]

    monkeypatch.setattr("harness.preflight.run_all", _fake_run_all)

    class _Proc:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    monkeypatch.setattr("subprocess.run",
                        lambda args, **kw: _Proc())
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "mimo", "--mode", "autonomous"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    assert "Preflight surfaced warnings" in result.output


def test_start_autonomous_ok_when_preflight_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-ok preflight proceeds silently to scheduler install."""
    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    monkeypatch.chdir(tmp_path)
    from harness.preflight import PreflightCheck

    monkeypatch.setattr("harness.preflight.run_all", lambda: [
        PreflightCheck(name="status_csv", severity="ok", message="fresh"),
    ])

    class _Proc:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    monkeypatch.setattr("subprocess.run",
                        lambda args, **kw: _Proc())
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "mimo", "--mode", "autonomous"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    assert "Preflight passed" in result.output


def test_start_interactive_skips_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interactive mode does NOT run preflight — that's only for
    autonomous-mode arming."""
    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    monkeypatch.chdir(tmp_path)

    call_count = {"n": 0}

    def _spy_run_all():
        call_count["n"] += 1
        return []

    monkeypatch.setattr("harness.preflight.run_all", _spy_run_all)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["start", "--orchestrator", "mimo", "--mode", "interactive"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    assert call_count["n"] == 0, "preflight should NOT run for interactive mode"
