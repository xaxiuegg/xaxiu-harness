"""Check entrypoint, flag-file writer, crisis scheduler, and Windows toast."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from harness._constants import _REPO_ROOT
from harness.session.recommender import Recommendation, recommend
from harness.session.signals import Signals, collect_signals

HANDOFF_DIR: Path = _REPO_ROOT / "coord" / "dev_loop"
HANDOFF_CRITICAL: Path = HANDOFF_DIR / "handoff_CRITICAL.md"
HANDOFF_RECOMMENDED: Path = HANDOFF_DIR / "handoff_recommended.md"

CRISIS_TASK_NAME = "XaxiuHarnessSessionCrisisCheck"


class CheckReport(BaseModel):
    timestamp: str
    signals: Signals
    recommendation: Recommendation
    reasons: list[str]
    handoff_file_written: bool


def _write_handoff_file(path: Path, rec: Recommendation, reasons: list[str], signals: Signals) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    lines: list[str] = [
        f"# Handoff {rec.upper()} — {now}",
        "",
        f"**Recommendation:** {rec.value}",
        "",
        "**Reasons:**",
    ]
    for r in reasons:
        lines.append(f"- {r}")
    lines.extend([
        "",
        "**Signals:**",
        "```json",
        json.dumps(signals.model_dump(mode="json"), indent=2),
        "```",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def check() -> CheckReport:
    """Run one health check, write flag files if warranted, and return the report.

    Per operator directive 2026-05-21: ONLY STRONGLY ("Heavy") and CRITICAL
    produce handoff_*.md files. SOFT is informational only — session is
    still healthy at SOFT, no handoff suggested.
    """
    signals = collect_signals()
    rec, reasons = recommend(signals)
    handoff_written = False
    if rec == Recommendation.CRITICAL:
        _write_handoff_file(HANDOFF_CRITICAL, rec, reasons, signals)
        handoff_written = True
    elif rec == Recommendation.STRONGLY:
        _write_handoff_file(HANDOFF_RECOMMENDED, rec, reasons, signals)
        handoff_written = True
    # SOFT explicitly skipped — no handoff file (operator directive 2026-05-21)
    return CheckReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        signals=signals,
        recommendation=rec,
        reasons=reasons,
        handoff_file_written=handoff_written,
    )


def ack_handoff() -> tuple[bool, str]:
    """Remove any pending handoff flag files."""
    removed: list[str] = []
    for p in (HANDOFF_CRITICAL, HANDOFF_RECOMMENDED):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    if removed:
        return True, f"Removed {', '.join(removed)}"
    return False, "No handoff files to acknowledge"


def _windows_toast(title: str, message: str) -> None:
    """Best-effort Windows toast / notification."""
    try:
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager,"
            "Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null;"
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            f"$template.GetElementsByTagName('text')[0].InnerText = '{title}';"
            f"$template.GetElementsByTagName('text')[1].InnerText = '{message}';"
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template);"
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('xaxiu-harness').Show($toast)"
        )
        subprocess.run(
            ["powershell.exe", "-Command", script],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


def crisis_check() -> CheckReport:
    """Run check and raise a Windows toast on CRITICAL."""
    report = check()
    if report.recommendation == Recommendation.CRITICAL:
        _windows_toast(
            "xaxiu-harness session handoff CRITICAL",
            "Crash imminent. Run 'harness session bootstrap' immediately.",
        )
    return report


def _pwsh() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _crisis_check_cmd() -> str:
    venv_python = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    py = str(venv_python) if venv_python.exists() else "python"
    return f"{py} -m harness session crisis-check"


def _build_register_crisis_script(cadence_minutes: int) -> str:
    action_cmd = _crisis_check_cmd()
    return f"""
$TaskName = '{CRISIS_TASK_NAME}'
$Action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "{action_cmd}"'
$Trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {cadence_minutes}) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Limited

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {{
    try {{ Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop }}
    catch {{ Write-Output ('FAILED: ' + $_.Exception.Message); exit 1 }}
}}

try {{
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Xaxiu Harness session crisis check (every {cadence_minutes} min)' -Force -ErrorAction Stop | Out-Null
    Write-Output 'OK'
}} catch {{
    Write-Output ('FAILED: ' + $_.Exception.Message)
    exit 1
}}
"""


def arm_crisis_check(cadence_minutes: int = 5) -> tuple[bool, str]:
    """Register the Windows Task Scheduler entry for periodic crisis checks."""
    ps = _pwsh()
    if ps is None:
        return False, "PowerShell not found — cannot register scheduled task"
    script = _build_register_crisis_script(cadence_minutes)
    result = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and "OK" in result.stdout:
        return True, f"Task '{CRISIS_TASK_NAME}' registered (every {cadence_minutes} min)"
    return False, result.stderr.strip() or result.stdout.strip() or "unknown error"
