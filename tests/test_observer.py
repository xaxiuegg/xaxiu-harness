"""Tests for the independent observer primitive (roster #20)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.observer.audit_prompt import build_audit_prompt
from harness.observer.cycle import _parse_json_array, _recent_git_commits, run_cycle, CycleReport
from harness.observer.flags import (
    Flag,
    FlagSeverity,
    ensure_flag_dirs,
    write_pending_flags,
    list_pending_flags,
    ack_flag,
    move_pending_to_handled,
)
from harness.observer.scheduler import register_tasks, unregister_tasks
from harness.observer.state import read_state, write_state, ObserverState, _StateFileCorruptError


# ---------------------------------------------------------------------------
# Flag model & helpers
# ---------------------------------------------------------------------------


def test_flag_severity_enum_values() -> None:
    assert FlagSeverity.LOW == "low"
    assert FlagSeverity.MED == "med"
    assert FlagSeverity.HIGH == "high"
    assert FlagSeverity.CRITICAL == "critical"


def test_flag_model_valid() -> None:
    f = Flag(
        id="FLAG-2026-05-20-1",
        severity=FlagSeverity.HIGH,
        category="claude_dispatch",
        summary="Dispatched to swarm/claude",
        detail="Packet routed to forbidden backend.",
        evidence=["log line 1"],
        raised_at=datetime.now(timezone.utc).isoformat(),
        cycle_id="cycle-1",
    )
    assert f.acknowledged is False
    assert f.id.startswith("FLAG-")


def test_flag_model_invalid_id_pattern() -> None:
    with pytest.raises(Exception):
        Flag(
            id="bad-id",
            severity=FlagSeverity.LOW,
            category="x",
            summary="x",
            detail="x",
            evidence=[],
            raised_at="2026-05-20T00:00:00+00:00",
            cycle_id="c1",
        )


# ---------------------------------------------------------------------------
# File-system helpers
# ---------------------------------------------------------------------------


def test_ensure_flag_dirs_creates_tree(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    result = ensure_flag_dirs(base)
    assert result == base
    assert (base / "cycles" / "handled").is_dir()
    assert (base / "daily").is_dir()
    assert (base / "flags").is_dir()


def test_write_and_list_pending_flags(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    ensure_flag_dirs(base)
    flags = [
        Flag(
            id="FLAG-2026-05-20-1",
            severity=FlagSeverity.HIGH,
            category="x",
            summary="s",
            detail="d",
            evidence=["e"],
            raised_at="2026-05-20T00:00:00+00:00",
            cycle_id="c1",
        ),
        Flag(
            id="FLAG-2026-05-20-2",
            severity=FlagSeverity.CRITICAL,
            category="y",
            summary="s2",
            detail="d2",
            evidence=["e2"],
            raised_at="2026-05-20T00:00:00+00:00",
            cycle_id="c1",
        ),
    ]
    written = write_pending_flags(flags, base)
    assert len(written) == 2

    pending = list_pending_flags(base)
    assert len(pending[FlagSeverity.HIGH]) == 1
    assert len(pending[FlagSeverity.CRITICAL]) == 1


def test_ack_flag_updates_file(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    ensure_flag_dirs(base)
    flags = [
        Flag(
            id="FLAG-2026-05-20-1",
            severity=FlagSeverity.HIGH,
            category="x",
            summary="s",
            detail="d",
            evidence=["e"],
            raised_at="2026-05-20T00:00:00+00:00",
            cycle_id="c1",
        )
    ]
    write_pending_flags(flags, base)
    updated = ack_flag("FLAG-2026-05-20-1", acknowledged_by="tester", observer_dir=base)
    assert updated is not None
    assert updated.acknowledged is True
    assert updated.acknowledged_by == "tester"

    # Re-read and verify
    pending = list_pending_flags(base)
    assert pending[FlagSeverity.HIGH][0].acknowledged is True


def test_ack_flag_not_found_returns_none(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    ensure_flag_dirs(base)
    assert ack_flag("FLAG-9999-99-99-99", observer_dir=base) is None


def test_move_pending_to_handled(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    ensure_flag_dirs(base)
    flags = [
        Flag(
            id="FLAG-2026-05-20-1",
            severity=FlagSeverity.HIGH,
            category="x",
            summary="s",
            detail="d",
            evidence=["e"],
            raised_at="2026-05-20T00:00:00+00:00",
            cycle_id="c1",
        )
    ]
    write_pending_flags(flags, base)
    dst = move_pending_to_handled(FlagSeverity.HIGH, base)
    assert dst is not None
    assert dst.name.startswith("HIGH_FLAG_")
    assert not (base / "HIGH_FLAG_PENDING.md").exists()


def test_move_pending_to_handled_no_file(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    ensure_flag_dirs(base)
    assert move_pending_to_handled(FlagSeverity.HIGH, base) is None


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------


def test_read_state_defaults(tmp_path: Path) -> None:
    state = read_state(tmp_path / "observer")
    assert state.armed is True
    assert state.status == "uninitialized"
    assert state.cadence_minutes == 60


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    state = ObserverState(
        armed=True,
        paused=False,
        cadence_minutes=30,
        daily_retro_time="22:00",
        status="ready",
        total_cycles=5,
    )
    write_state(state, base)
    loaded = read_state(base)
    assert loaded.status == "ready"
    assert loaded.cadence_minutes == 30
    assert loaded.total_cycles == 5


def test_read_state_corrupt_file(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    base.mkdir(parents=True, exist_ok=True)
    (base / "observer-state.json").write_text("not json", encoding="utf-8")
    with pytest.raises(_StateFileCorruptError):
        read_state(base)


# ---------------------------------------------------------------------------
# Audit prompt
# ---------------------------------------------------------------------------


def test_build_audit_prompt_contains_rules() -> None:
    prompt = build_audit_prompt(
        recent_log=[],
        status_rows=[],
        git_log=[],
        cycle_id="c1",
        audit_window_minutes=60,
    )
    assert "Never dispatch to 'swarm/claude'" in prompt
    assert "JSON array" in prompt
    assert "c1" in prompt


def test_build_audit_prompt_with_custom_rules() -> None:
    prompt = build_audit_prompt(
        recent_log=[],
        status_rows=[],
        git_log=[],
        cycle_id="c2",
        audit_window_minutes=30,
        rules=["6. Custom rule"],
    )
    assert "Custom rule" in prompt


def test_build_audit_prompt_formats_log() -> None:
    log = [{"timestamp": "t1", "project": "p", "backend": "deepseek", "model": "m", "outcome": "ok", "fallback_to": ""}]
    prompt = build_audit_prompt(
        recent_log=log,
        status_rows=[],
        git_log=[],
        cycle_id="c1",
        audit_window_minutes=60,
    )
    assert "deepseek" in prompt


# ---------------------------------------------------------------------------
# Cycle parsing helpers
# ---------------------------------------------------------------------------


def test_parse_json_array_empty() -> None:
    assert _parse_json_array("") == []
    assert _parse_json_array("not json") == []


def test_parse_json_array_plain() -> None:
    assert _parse_json_array('[{"severity":"high"}]') == [{"severity": "high"}]


def test_parse_json_array_with_markdown_fences() -> None:
    text = '```json\n[{"a":1}]\n```'
    assert _parse_json_array(text) == [{"a": 1}]


def test_parse_json_array_skips_non_dict_items() -> None:
    assert _parse_json_array('[1, {"a":1}, "str"]') == [{"a": 1}]


# ---------------------------------------------------------------------------
# Cycle runner (with mocked dispatch)
# ---------------------------------------------------------------------------


def test_run_cycle_no_findings(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    mock_dispatch = MagicMock()
    mock_dispatch.return_value = MagicMock(
        success=True,
        engine_used="swarm/deepseek",
        fallback_chain=[],
        text="[]",
        error=None,
        dispatch_id="d1",
    )
    report = run_cycle(
        engine="swarm/deepseek",
        audit_window_minutes=60,
        observer_dir=base,
        dispatch_fn=mock_dispatch,
    )
    assert report.findings_count == 0
    assert len(report.flags_raised) == 0
    assert report.report_path is not None
    assert report.report_path.exists()


def test_run_cycle_with_findings(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    mock_dispatch = MagicMock()
    mock_dispatch.return_value = MagicMock(
        success=True,
        engine_used="swarm/deepseek",
        fallback_chain=[],
        text=json.dumps([
            {
                "severity": "high",
                "category": "claude_dispatch",
                "summary": "Bad dispatch",
                "detail": "Routed to claude",
                "evidence": ["log"],
            }
        ]),
        error=None,
        dispatch_id="d2",
    )
    report = run_cycle(
        engine="swarm/deepseek",
        audit_window_minutes=60,
        observer_dir=base,
        dispatch_fn=mock_dispatch,
    )
    assert report.findings_count == 1
    assert len(report.flags_raised) == 1
    assert report.flags_raised[0].severity == FlagSeverity.HIGH
    assert (base / "HIGH_FLAG_PENDING.md").exists()


def test_run_cycle_critical_finding(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    mock_dispatch = MagicMock()
    mock_dispatch.return_value = MagicMock(
        success=True,
        engine_used="swarm/gemini",
        fallback_chain=[],
        text=json.dumps([
            {
                "severity": "critical",
                "category": "secret_leak",
                "summary": "API key leaked",
                "detail": "Key in log",
                "evidence": ["line"],
            }
        ]),
        error=None,
        dispatch_id="d3",
    )
    report = run_cycle(
        engine="swarm/gemini",
        audit_window_minutes=60,
        observer_dir=base,
        dispatch_fn=mock_dispatch,
    )
    assert report.flags_raised[0].severity == FlagSeverity.CRITICAL
    assert (base / "CRITICAL_FLAG_PENDING.md").exists()


def test_run_cycle_dispatch_error(tmp_path: Path) -> None:
    base = tmp_path / "observer"
    mock_dispatch = MagicMock()
    mock_dispatch.return_value = MagicMock(
        success=False,
        engine_used="swarm/deepseek",
        fallback_chain=["swarm/deepseek"],
        text="",
        error="timeout",
        dispatch_id="d4",
    )
    report = run_cycle(
        engine="swarm/deepseek",
        audit_window_minutes=60,
        observer_dir=base,
        dispatch_fn=mock_dispatch,
    )
    assert report.error == "timeout"
    assert report.findings_count == 0


# ---------------------------------------------------------------------------
# Scheduler (PowerShell not available in CI -> should gracefully degrade)
# ---------------------------------------------------------------------------


def test_register_tasks_no_powershell() -> None:
    with patch("harness.observer.scheduler._pwsh", return_value=None):
        ok, msg = register_tasks()
    assert ok is False
    assert "PowerShell not found" in msg


def test_unregister_tasks_no_powershell() -> None:
    with patch("harness.observer.scheduler._pwsh", return_value=None):
        ok, msg = unregister_tasks()
    assert ok is False
    assert "PowerShell not found" in msg


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

runner = CliRunner()


def test_cli_observer_init() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            result = runner.invoke(cli, ["observer", "init", "--cadence-minutes", "30"])
            assert result.exit_code == 0
            assert "observer initialized" in result.output
            assert "30 min" in result.output
            assert (observer_dir / "observer-state.json").exists()


def test_cli_observer_status_uninitialized() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            result = runner.invoke(cli, ["observer", "status"])
            assert result.exit_code == 0
            assert "uninitialized" in result.output


def test_cli_observer_arm_disarm() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            runner.invoke(cli, ["observer", "init"])
            result = runner.invoke(cli, ["observer", "arm"])
            assert result.exit_code == 0
            assert "armed" in result.output

            result2 = runner.invoke(cli, ["observer", "disarm"])
            assert result2.exit_code == 0
            assert "disarmed" in result2.output


def test_cli_observer_pause_resume() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            runner.invoke(cli, ["observer", "init"])
            result = runner.invoke(cli, ["observer", "pause"])
            assert result.exit_code == 0
            assert "paused" in result.output

            result2 = runner.invoke(cli, ["observer", "resume"])
            assert result2.exit_code == 0
            assert "resumed" in result2.output


def test_cli_observer_arm_before_init_fails() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            result = runner.invoke(cli, ["observer", "arm"])
            assert result.exit_code == 1
            assert "not initialized" in result.output


def test_cli_observer_flags_empty() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            runner.invoke(cli, ["observer", "init"])
            result = runner.invoke(cli, ["observer", "flags"])
            assert result.exit_code == 0
            assert "no pending flags" in result.output


def test_cli_observer_ack_missing_flag() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            runner.invoke(cli, ["observer", "init"])
            result = runner.invoke(cli, ["observer", "ack", "FLAG-9999-99-99-99"])
            assert result.exit_code == 1
            assert "not found" in result.output


def test_cli_observer_cycle_now_not_initialized() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            result = runner.invoke(cli, ["observer", "cycle-now"])
            assert result.exit_code == 1
            assert "not initialized" in result.output


def test_cli_observer_cycle_now_paused() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            runner.invoke(cli, ["observer", "init"])
            runner.invoke(cli, ["observer", "pause"])
            result = runner.invoke(cli, ["observer", "cycle-now"])
            assert result.exit_code == 0
            assert "paused" in result.output


def test_cli_observer_cycle_now_runs_cycle() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.cycle.run_cycle") as mock_cycle:
            mock_cycle.return_value = CycleReport(
                cycle_id="c1",
                started_at="t1",
                ended_at="t2",
                engine_used="swarm/deepseek",
                audit_window_minutes=60,
                prompt_size_chars=100,
                response_size_chars=50,
                findings_count=0,
                flags_raised=[],
                report_path=None,
                error=None,
            )
            runner.invoke(cli, ["observer", "init"])
            result = runner.invoke(cli, ["observer", "cycle-now"])
            assert result.exit_code == 0
            assert "c1 complete" in result.output
            mock_cycle.assert_called_once()


def test_cli_observer_cycle_now_dry_run() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            runner.invoke(cli, ["observer", "init"])
            result = runner.invoke(cli, ["--mode", "dry_run", "observer", "cycle-now"])
            assert result.exit_code == 0
            assert "dry-run: would run observer cycle" in result.output


def test_cli_observer_flags_with_pending() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            runner.invoke(cli, ["observer", "init"])
            flag = Flag(
                id="FLAG-2026-05-20-99",
                severity=FlagSeverity.HIGH,
                category="test",
                summary="test flag",
                detail="detail",
                evidence=["ev"],
                raised_at="2026-05-20T00:00:00+00:00",
                cycle_id="c99",
            )
            write_pending_flags([flag], observer_dir)
            result = runner.invoke(cli, ["observer", "flags"])
            assert result.exit_code == 0
            assert "FLAG-2026-05-20-99" in result.output


def test_cli_observer_init_idempotent() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            r1 = runner.invoke(cli, ["observer", "init"])
            assert r1.exit_code == 0
            r2 = runner.invoke(cli, ["observer", "init"])
            assert r2.exit_code == 0
            assert "observer initialized" in r2.output


def test_cli_observer_scheduler_install_no_ps() -> None:
    with runner.isolated_filesystem() as fs:
        observer_dir = Path(fs) / "observer"
        with patch("harness.observer.state.DEFAULT_OBSERVER_DIR", observer_dir), \
             patch("harness.observer.flags.DEFAULT_OBSERVER_DIR", observer_dir):
            runner.invoke(cli, ["observer", "init"])
        with patch("harness.observer.scheduler._pwsh", return_value=None):
            result = runner.invoke(cli, ["observer", "install-scheduler"])
        assert result.exit_code == 1
        assert "PowerShell not found" in result.output


def test_cli_observer_scheduler_uninstall_no_ps() -> None:
    with runner.isolated_filesystem() as fs:
        with patch("harness.observer.scheduler._pwsh", return_value=None):
            result = runner.invoke(cli, ["observer", "uninstall-scheduler"])
        assert result.exit_code == 1
        assert "PowerShell not found" in result.output


def test_run_cycle_skips_low_and_med_flags(tmp_path: Path) -> None:
    """LOW and MED findings should NOT create pending files."""
    base = tmp_path / "observer"
    mock_dispatch = MagicMock()
    mock_dispatch.return_value = MagicMock(
        success=True,
        engine_used="swarm/deepseek",
        fallback_chain=[],
        text=json.dumps([
            {"severity": "low", "category": "x", "summary": "s", "detail": "d", "evidence": []},
            {"severity": "med", "category": "y", "summary": "s2", "detail": "d2", "evidence": []},
        ]),
        error=None,
        dispatch_id="d5",
    )
    report = run_cycle(
        engine="swarm/deepseek",
        audit_window_minutes=60,
        observer_dir=base,
        dispatch_fn=mock_dispatch,
    )
    assert len(report.flags_raised) == 2
    assert not (base / "HIGH_FLAG_PENDING.md").exists()
    assert not (base / "CRITICAL_FLAG_PENDING.md").exists()


# ---------------------------------------------------------------------------
# Scheduler helpers (direct coverage for observer.scheduler)
# ---------------------------------------------------------------------------


def test_observer_pwsh_returns_pwsh() -> None:
    with patch(
        "harness.observer.scheduler.shutil.which",
        side_effect=lambda name: "C:\\pwsh" if name == "pwsh" else None,
    ):
        from harness.observer.scheduler import _pwsh
        assert _pwsh() == "C:\\pwsh"


def test_observer_pwsh_returns_powershell() -> None:
    with patch(
        "harness.observer.scheduler.shutil.which",
        side_effect=lambda name: "C:\\powershell" if name == "powershell" else None,
    ):
        from harness.observer.scheduler import _pwsh
        assert _pwsh() == "C:\\powershell"


def test_observer_pwsh_returns_none() -> None:
    with patch("harness.observer.scheduler.shutil.which", return_value=None):
        from harness.observer.scheduler import _pwsh
        assert _pwsh() is None


def test_observer_project_root() -> None:
    from harness.observer.scheduler import _project_root
    with patch("harness.observer.scheduler._REPO_ROOT", Path("C:\\repo")):
        assert _project_root() == "C:\\repo"


def test_observer_cmd_uses_venv(tmp_path: Path) -> None:
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    from harness.observer.scheduler import _observer_cmd
    with patch("harness.observer.scheduler._REPO_ROOT", tmp_path):
        cmd = _observer_cmd()
    assert str(venv_python) in cmd
    assert cmd.endswith(" -m harness observer cycle-now")


def test_observer_cmd_falls_back(tmp_path: Path) -> None:
    from harness.observer.scheduler import _observer_cmd
    with patch("harness.observer.scheduler._REPO_ROOT", tmp_path):
        cmd = _observer_cmd()
    assert cmd == "python -m harness observer cycle-now"


def test_daily_retro_cmd_uses_venv(tmp_path: Path) -> None:
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    from harness.observer.scheduler import _daily_retro_cmd
    with patch("harness.observer.scheduler._REPO_ROOT", tmp_path):
        cmd = _daily_retro_cmd()
    assert str(venv_python) in cmd
    assert cmd.endswith(" -m harness observer daily-retro")


def test_daily_retro_cmd_falls_back(tmp_path: Path) -> None:
    from harness.observer.scheduler import _daily_retro_cmd
    with patch("harness.observer.scheduler._REPO_ROOT", tmp_path):
        cmd = _daily_retro_cmd()
    assert cmd == "python -m harness observer daily-retro"


def test_build_ps_script_task_name_interpolation() -> None:
    from harness.observer.scheduler import _build_ps_script
    script = _build_ps_script(
        task_name="XaxiuHarnessObserverCycle",
        trigger_ps="New-ScheduledTaskTrigger -Daily -At '23:00'",
        action_cmd="python -m harness observer cycle-now",
        description="test desc",
    )
    assert "$TaskName = 'XaxiuHarnessObserverCycle'" in script
    assert "New-ScheduledTaskTrigger -Daily -At '23:00'" in script
    assert "python -m harness observer cycle-now" in script
    assert "test desc" in script
    assert "-RunLevel Limited" in script
    assert "try {" in script
    assert "catch {" in script


def test_register_tasks_mixed_success_cycle_ok_retro_fail() -> None:
    from harness.observer.scheduler import register_tasks
    with patch("harness.observer.scheduler._pwsh", return_value="powershell.exe"), \
         patch("harness.observer.scheduler.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="OK\n", stderr=""),
            MagicMock(returncode=1, stdout="FAIL", stderr=""),
        ]
        ok, msg = register_tasks()
    assert ok is False
    assert "Cycle task OK" in msg
    assert "retro task failed" in msg


def test_register_tasks_mixed_success_retro_ok_cycle_fail() -> None:
    from harness.observer.scheduler import register_tasks
    with patch("harness.observer.scheduler._pwsh", return_value="powershell.exe"), \
         patch("harness.observer.scheduler.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="CYCLE_FAIL", stderr=""),
            MagicMock(returncode=0, stdout="OK\n", stderr=""),
        ]
        ok, msg = register_tasks()
    assert ok is False
    assert "retro task OK" in msg
    assert "cycle task failed" in msg


def test_register_tasks_both_fail() -> None:
    from harness.observer.scheduler import register_tasks
    with patch("harness.observer.scheduler._pwsh", return_value="powershell.exe"), \
         patch("harness.observer.scheduler.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="CYCLE_FAIL", stderr=""),
            MagicMock(returncode=1, stdout="RETRO_FAIL", stderr=""),
        ]
        ok, msg = register_tasks()
    assert ok is False
    assert "cycle task failed: CYCLE_FAIL" in msg
    assert "retro task failed: RETRO_FAIL" in msg


def test_unregister_tasks_iterates_both() -> None:
    from harness.observer.scheduler import unregister_tasks
    with patch("harness.observer.scheduler._pwsh", return_value="powershell.exe"), \
         patch("harness.observer.scheduler.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="OK removed cycle", stderr=""),
            MagicMock(returncode=0, stdout="SKIP retro not found", stderr=""),
            MagicMock(returncode=0, stdout="SKIP chat not found", stderr=""),
        ]
        ok, msg = unregister_tasks()
    assert ok is True
    assert "OK removed cycle" in msg
    assert "SKIP retro not found" in msg


def test_register_tasks_both_ok() -> None:
    from harness.observer.scheduler import register_tasks
    with patch("harness.observer.scheduler._pwsh", return_value="powershell.exe"), \
         patch("harness.observer.scheduler.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="OK\n", stderr=""),
            MagicMock(returncode=0, stdout="OK\n", stderr=""),
        ]
        ok, msg = register_tasks(cadence_minutes=45, daily_time="22:30")
    assert ok is True
    assert "45 min" in msg
    assert "22:30" in msg
import json
from unittest.mock import MagicMock


def test_dry_run_writes_expected_json_keys(tmp_path):
    """--dry-run should write a JSON file with the required keys."""
    from harness.observer.cycle import run_cycle

    report = run_cycle(
        observer_dir=tmp_path,
        dry_run=True,
    )
    assert report.report_path is not None
    data = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {
        "prompt_first_200_chars",
        "prompt_length_chars",
        "engine",
        "output_path",
        "recent_event_count",
    }


def test_dry_run_does_not_dispatch(tmp_path):
    """--dry-run must not call the dispatch function."""
    from harness.observer.cycle import run_cycle

    mock_dispatch = MagicMock()
    run_cycle(
        observer_dir=tmp_path,
        dry_run=True,
        dispatch_fn=mock_dispatch,
    )
    mock_dispatch.assert_not_called()


def test_dry_run_prompt_first_200_chars(tmp_path):
    """prompt_first_200_chars must be exactly the first 200 chars, no ellipsis or folding."""
    from harness.observer.cycle import run_cycle
    from harness.observer.audit_prompt import build_audit_prompt

    report = run_cycle(
        observer_dir=tmp_path,
        dry_run=True,
    )
    data = json.loads(report.report_path.read_text(encoding="utf-8"))

    # Build the same prompt to verify
    prompt = build_audit_prompt(
        recent_log=[],
        status_rows=[],
        git_log=[],
        cycle_id=report.cycle_id,
        audit_window_minutes=60,
    )
    expected = prompt[:200]
    assert data["prompt_first_200_chars"] == expected
    assert len(data["prompt_first_200_chars"]) == min(200, len(expected))


# ---------------------------------------------------------------------------
# WIRE-AUDIT-CHAT-GLOBAL-FALLBACK (2026-05-22) — W3-D
# ---------------------------------------------------------------------------

def test_latest_session_jsonl_falls_back_globally(tmp_path, monkeypatch) -> None:
    """When cwd-slug dir has no jsonl, fall back to the most-recently-modified
    jsonl across all other Claude project dirs."""
    from harness.observer import chat as chat_mod

    projects = tmp_path / "home" / ".claude" / "projects"
    projects.mkdir(parents=True)
    cwd_slug = "D--xaxiu-harness-standalone"
    (projects / cwd_slug).mkdir()
    other_dir = projects / "d--Projects"
    other_dir.mkdir()
    other_jsonl = other_dir / "abc.jsonl"
    other_jsonl.write_text('{"role":"user","content":"hi"}\n', encoding="utf-8")

    monkeypatch.setattr(chat_mod, "_claude_projects_dir", lambda: projects)
    monkeypatch.setattr(chat_mod, "_cwd_slug", lambda: cwd_slug)

    result = chat_mod._latest_session_jsonl()
    assert result == other_jsonl


def test_latest_session_jsonl_returns_none_when_no_jsonl_anywhere(tmp_path, monkeypatch) -> None:
    """No jsonl in any project dir → returns None (audit returns empty report,
    no exception)."""
    from harness.observer import chat as chat_mod

    projects = tmp_path / "home" / ".claude" / "projects"
    projects.mkdir(parents=True)
    (projects / "D--cwd").mkdir()
    (projects / "D--other").mkdir()

    monkeypatch.setattr(chat_mod, "_claude_projects_dir", lambda: projects)
    monkeypatch.setattr(chat_mod, "_cwd_slug", lambda: "D--cwd")

    assert chat_mod._latest_session_jsonl() is None