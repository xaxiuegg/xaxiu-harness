"""Task Scheduler integration for observer autonomous loops.

Mirrors the pattern established in ``bin/register-dev-loop-task.ps1`` but
exposes Python-callable ``register_tasks`` and ``unregister_tasks``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from harness._constants import _REPO_ROOT

TASK_NAME_PREFIX = "XaxiuHarness"


def _pwsh() -> str | None:
    """Return the path to PowerShell (pwsh or powershell)."""
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _project_root() -> str:
    return str(_REPO_ROOT)


def _observer_cmd() -> str:
    """The CLI invocation string used inside scheduled tasks."""
    # Prefer running via the project's python so we don't depend on PATH
    venv_python = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        py = str(venv_python)
    else:
        py = "python"
    return f'{py} -m harness observer cycle-now'


def _daily_retro_cmd() -> str:
    venv_python = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        py = str(venv_python)
    else:
        py = "python"
    return f'{py} -m harness observer daily-retro'


def _chat_audit_cmd() -> str:
    venv_python = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        py = str(venv_python)
    else:
        py = "python"
    return f'{py} -m harness observer audit-chat'


def _build_ps_script(
    task_name: str,
    trigger_ps: str,
    action_cmd: str,
    description: str,
) -> str:
    """Return a PowerShell script that idempotently registers a task.

    Uses ``-RunLevel Limited`` (no admin) so the registration succeeds
    in a non-elevated shell.  Wraps Register-ScheduledTask in
    try/catch with ``-ErrorAction Stop`` so silent failures (the prior
    bug) become explicit non-OK output.
    """
    return f"""
$TaskName = '{task_name}'
$Action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""{action_cmd}""'
$Trigger  = {trigger_ps}
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Limited

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {{
    try {{ Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop }}
    catch {{ Write-Output ('FAILED: ' + $_.Exception.Message); exit 1 }}
}}

try {{
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description '{description}' -Force -ErrorAction Stop | Out-Null
    Write-Output 'OK'
}} catch {{
    Write-Output ('FAILED: ' + $_.Exception.Message)
    exit 1
}}
"""


def register_chat_audit_task(
    cadence_minutes: int = 60,
    task_prefix: str = TASK_NAME_PREFIX,
) -> bool:
    """Register the chat-observer audit task in Windows Task Scheduler."""
    ps = _pwsh()
    if ps is None:
        return False

    trigger = (
        f"New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {cadence_minutes}) "
        f"-RepetitionDuration (New-TimeSpan -Days 3650)"
    )
    script = _build_ps_script(
        task_name=f"{task_prefix}ObserverChatAudit",
        trigger_ps=trigger,
        action_cmd=_chat_audit_cmd(),
        description=f"Xaxiu Harness chat-observer audit (every {cadence_minutes} min)",
    )

    result = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and "OK" in result.stdout


def register_tasks(
    cadence_minutes: int = 60,
    daily_time: str = "23:00",
    include_chat: bool = False,
) -> tuple[bool, str]:
    """Register the two observer scheduled tasks.

    Parameters
    ----------
    cadence_minutes :
        Minutes between cycle runs (default 60).
    daily_time :
        Local time for the daily retro (HH:MM, default 23:00).

    Returns
    -------
    (success, message)
    """
    ps = _pwsh()
    if ps is None:
        return False, "PowerShell not found — cannot register scheduled tasks"

    # Cycle task — repeats every cadence_minutes
    cycle_trigger = (
        f"New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {cadence_minutes}) "
        f"-RepetitionDuration (New-TimeSpan -Days 3650)"
    )
    cycle_script = _build_ps_script(
        task_name="XaxiuHarnessObserverCycle",
        trigger_ps=cycle_trigger,
        action_cmd=_observer_cmd(),
        description=f"Xaxiu Harness observer audit cycle (every {cadence_minutes} min)",
    )

    result_cycle = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cycle_script],
        capture_output=True,
        text=True,
    )
    ok_cycle = result_cycle.returncode == 0 and "OK" in result_cycle.stdout

    # Daily retro task
    retro_trigger = f"New-ScheduledTaskTrigger -Daily -At '{daily_time}'"
    retro_script = _build_ps_script(
        task_name="XaxiuHarnessObserverDailyRetro",
        trigger_ps=retro_trigger,
        action_cmd=_daily_retro_cmd(),
        description="Xaxiu Harness observer daily retro",
    )

    result_retro = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", retro_script],
        capture_output=True,
        text=True,
    )
    ok_retro = result_retro.returncode == 0 and "OK" in result_retro.stdout

    ok_chat = True
    chat_msg = ""
    if include_chat:
        ok_chat = register_chat_audit_task(cadence_minutes=cadence_minutes)
        chat_msg = "chat audit registered" if ok_chat else "chat audit failed"

    if ok_cycle and ok_retro and ok_chat:
        msg = f"Tasks registered (cycle every {cadence_minutes} min, retro at {daily_time})"
        if include_chat:
            msg += f", {chat_msg}"
        return True, msg
    parts: list[str] = []
    if ok_cycle:
        parts.append("Cycle task OK")
    else:
        parts.append(f"cycle task failed: {result_cycle.stderr.strip() or result_cycle.stdout.strip()}")
    if ok_retro:
        parts.append("retro task OK")
    else:
        parts.append(f"retro task failed: {result_retro.stderr.strip() or result_retro.stdout.strip()}")
    if include_chat:
        parts.append(chat_msg)
    return False, "; ".join(parts)


def unregister_tasks() -> tuple[bool, str]:
    """Remove both observer scheduled tasks.

    Returns
    -------
    (success, message)
    """
    ps = _pwsh()
    if ps is None:
        return False, "PowerShell not found — cannot unregister scheduled tasks"

    results: list[str] = []
    for name in ("XaxiuHarnessObserverCycle", "XaxiuHarnessObserverDailyRetro", "XaxiuHarnessObserverChatAudit"):
        script = f"""
$TaskName = '{name}'
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {{
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output 'OK removed {name}'
}} else {{
    Write-Output 'SKIP {name} not found'
}}
"""
        result = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
        )
        out = result.stdout.strip()
        results.append(out if out else result.stderr.strip())

    return True, "; ".join(results)
