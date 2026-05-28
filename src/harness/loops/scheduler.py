"""Windows Task Scheduler integration for the autonomous dev loop.

Mirrors ``harness.observer.scheduler`` — same PowerShell + Register-ScheduledTask
pattern, but registers a single recurring task that invokes ``harness loop tick``.
"""

from __future__ import annotations

import shutil
import subprocess

from harness._constants import _REPO_ROOT

TASK_NAME = "XaxiuHarnessLoopTick"


def _pwsh() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _loop_tick_cmd() -> str:
    venv_python = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    py = str(venv_python) if venv_python.exists() else "python"
    return f"{py} -m harness loop tick"


def _build_register_script(cadence_minutes: int) -> str:
    action_cmd = _loop_tick_cmd()
    # W14-LOOP-CWD-FIX (2026-05-27): include -WorkingDirectory so Task
    # Scheduler doesn't run the action from `C:\Windows\System32` (the
    # default).  Without this, `python -m harness loop tick` blew up
    # with `PermissionError: [WinError 5] Access is denied: 'coord'`
    # because the loop state path was cwd-relative.  Belt-and-suspenders
    # with the cli.py default-path fix anchoring to _REPO_ROOT.
    working_dir = str(_REPO_ROOT)
    return f"""
$TaskName = '{TASK_NAME}'
$Action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""{action_cmd}""' -WorkingDirectory '{working_dir}'
$Trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {cadence_minutes}) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Limited

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {{
    try {{ Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop }}
    catch {{ Write-Output ('FAILED: ' + $_.Exception.Message); exit 1 }}
}}

try {{
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Xaxiu Harness autonomous loop tick (every {cadence_minutes} min)' -Force -ErrorAction Stop | Out-Null
    Write-Output 'OK'
}} catch {{
    Write-Output ('FAILED: ' + $_.Exception.Message)
    exit 1
}}
"""


def register_loop_task(cadence_minutes: int = 30) -> tuple[bool, str]:
    """Register the Windows Task Scheduler entry that runs ``harness loop tick``.

    Returns ``(ok, message)``.
    """
    ps = _pwsh()
    if ps is None:
        return False, "PowerShell not found — cannot register scheduled task"
    script = _build_register_script(cadence_minutes)
    result = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and "OK" in result.stdout:
        return True, f"Task '{TASK_NAME}' registered (every {cadence_minutes} min)"
    return False, result.stderr.strip() or result.stdout.strip() or "unknown error"


def unregister_loop_task() -> tuple[bool, str]:
    """Remove the loop tick scheduled task."""
    ps = _pwsh()
    if ps is None:
        return False, "PowerShell not found — cannot unregister scheduled task"
    script = f"""
$TaskName = '{TASK_NAME}'
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
        capture_output=True,
        text=True,
    )
    out = result.stdout.strip()
    return True, out or result.stderr.strip()


def is_registered(*, timeout_sec: float = 5.0) -> bool:
    """Return True iff ``XaxiuHarnessLoopTick`` is registered.

    W9-CLI-TIMEOUT-BUDGET 2026-05-24: bounded by ``timeout_sec``
    (default 5s) and returns False on timeout instead of hanging
    the caller.  The master-audit panel showed preflight + today
    blowing past 30s when this check stalled under contention.
    """
    ps = _pwsh()
    if ps is None:
        return False
    script = (
        f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
        "if ($t) { 'YES' } else { 'NO' }"
    )
    try:
        result = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return False
    return "YES" in result.stdout
