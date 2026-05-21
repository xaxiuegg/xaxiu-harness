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
