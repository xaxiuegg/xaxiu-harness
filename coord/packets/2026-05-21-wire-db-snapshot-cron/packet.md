# WIRE-DB-SNAPSHOT-CRON — schedule hourly _take_snapshot via Task Scheduler

## Goal

`harness.state.db._take_snapshot` exists and works, but nothing schedules
it.  On first DB corruption the auto-restore code path has no snapshot
to restore from.  Add a `harness state snapshot` CLI verb + a scheduler
helper so the operator can register an hourly Task Scheduler entry.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New CLI subcommand in `state` group

In `src/harness/cli.py`, find `@state.command(name="inspect")` (existing
state-group subcommand).  Add NEW siblings AFTER it:

```python
@state.command(name="snapshot")
@click.option("--db-path", default=None, type=click.Path(path_type=Path),
              help="Path to history.db (defaults to STATE_DIR/history.db).")
def state_snapshot_cmd(db_path: Path | None) -> None:
    """Take a snapshot of history.db into STATE_DIR/db_snapshots/."""
    from harness._constants import DB_FILE_NAME, STATE_DIR
    from harness.state.db import _take_snapshot
    target = db_path or (STATE_DIR / DB_FILE_NAME)
    snap = _take_snapshot(target)
    if snap is None:
        click.echo(f"no snapshot taken (db missing or unreadable at {target})")
        sys.exit(1)
    click.echo(f"snapshot: {snap}")


@state.command(name="snapshot-schedule")
@click.option("--cadence-minutes", default=60, type=int,
              help="Minutes between snapshots (default 60).")
def state_snapshot_schedule_cmd(cadence_minutes: int) -> None:
    """Register a Windows Scheduled Task to call `state snapshot` every N min."""
    from harness.state.db_scheduler import register_snapshot_task
    ok, msg = register_snapshot_task(cadence_minutes=cadence_minutes)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@state.command(name="snapshot-unschedule")
def state_snapshot_unschedule_cmd() -> None:
    """Remove the snapshot Scheduled Task."""
    from harness.state.db_scheduler import unregister_snapshot_task
    ok, msg = unregister_snapshot_task()
    click.echo(msg)
    sys.exit(0 if ok else 1)
```

### 2. New scheduler module `src/harness/state/db_scheduler.py`

```python
"""Task Scheduler integration for hourly db snapshots (WIRE-DB-SNAPSHOT-CRON)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from harness._constants import TASK_NAME_PREFIX


_TASK_NAME = f"{TASK_NAME_PREFIX}DbSnapshot"


def _pwsh() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def _build_ps_script(cadence_minutes: int) -> str:
    """Build the Register-ScheduledTask PowerShell payload."""
    # Action calls `harness state snapshot` — runs whichever Python is on PATH.
    return f"""
$TaskName = '{_TASK_NAME}'
$Action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c harness state snapshot >> "%TEMP%\\xaxiu-harness-snapshot.log" 2>&1'
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {cadence_minutes}) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {{ Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }}
try {{
  Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Limited -ErrorAction Stop | Out-Null
  Write-Output 'OK'
}} catch {{
  Write-Output ("FAIL: " + $_.Exception.Message)
}}
"""


def register_snapshot_task(cadence_minutes: int = 60) -> tuple[bool, str]:
    ps = _pwsh()
    if ps is None:
        return False, "PowerShell not found — snapshot scheduling unavailable"
    script = _build_ps_script(cadence_minutes=cadence_minutes)
    result = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True,
    )
    ok = result.returncode == 0 and "OK" in result.stdout
    return ok, result.stdout.strip() or result.stderr.strip() or "(no output)"


def unregister_snapshot_task() -> tuple[bool, str]:
    ps = _pwsh()
    if ps is None:
        return False, "PowerShell not found"
    script = f"""
$TaskName = '{_TASK_NAME}'
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {{
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Output 'OK removed'
}} else {{
  Write-Output 'SKIP not found'
}}
"""
    result = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True,
    )
    ok = result.returncode == 0
    return ok, result.stdout.strip() or "(no output)"
```

### 3. Tests

`tests/test_db_snapshot_cron.py`:

```python
"""Tests for WIRE-DB-SNAPSHOT-CRON."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_state_snapshot_taken(runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
    from harness.state import db as db_module
    monkeypatch.setattr(db_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(db_module, "_connection", None)
    db_path = tmp_path / "history.db"
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE x (id INTEGER);")
    conn.commit()
    conn.close()
    result = runner.invoke(cli, ["state", "snapshot", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "snapshot:" in result.output


def test_cli_state_snapshot_missing_db_exits_1(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, [
        "state", "snapshot", "--db-path", str(tmp_path / "nope.db"),
    ])
    assert result.exit_code == 1
    assert "no snapshot" in result.output


def test_register_snapshot_task_ok() -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "_pwsh", return_value="powershell.exe"), \
         patch.object(db_scheduler, "subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
        ok, msg = db_scheduler.register_snapshot_task(cadence_minutes=30)
    assert ok is True
    assert "OK" in msg


def test_register_snapshot_task_no_pwsh() -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "_pwsh", return_value=None):
        ok, msg = db_scheduler.register_snapshot_task()
    assert ok is False
    assert "PowerShell not found" in msg


def test_unregister_snapshot_task_ok() -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "_pwsh", return_value="powershell.exe"), \
         patch.object(db_scheduler, "subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0, stdout="OK removed\n", stderr="")
        ok, msg = db_scheduler.unregister_snapshot_task()
    assert ok is True


def test_cli_state_snapshot_schedule(runner: CliRunner) -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "register_snapshot_task",
                      return_value=(True, "OK")):
        result = runner.invoke(cli, ["state", "snapshot-schedule",
                                     "--cadence-minutes", "60"])
    assert result.exit_code == 0


def test_cli_state_snapshot_unschedule(runner: CliRunner) -> None:
    from harness.state import db_scheduler
    with patch.object(db_scheduler, "unregister_snapshot_task",
                      return_value=(True, "OK removed")):
        result = runner.invoke(cli, ["state", "snapshot-unschedule"])
    assert result.exit_code == 0
```

## Acceptance

- `python -m pytest tests/test_db_snapshot_cron.py` — green.
- Full suite stays green.

## Constraints

- DO NOT modify `_take_snapshot` or `init_db`.
- DO NOT touch observer/scheduler.py.
- Stdlib only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
