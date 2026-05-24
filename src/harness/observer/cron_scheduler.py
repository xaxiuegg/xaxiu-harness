"""W11-CROSS-PLATFORM-OBSERVER: cron-based observer scheduler for Linux + macOS.

Pairs with the existing harness.observer.scheduler (Windows Task
Scheduler) — same public surface (register/unregister + scheduler_status)
but uses crontab for *nix.  Selected at runtime via sys.platform check.

Schema for cron entries (per task):
    # HARNESS_OBSERVER:<task_name>
    <minute> <hour> * * * <command_with_absolute_path>

The marker comment lets unregister() find + remove only harness-owned
entries without touching the operator's other cron jobs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from harness._constants import _REPO_ROOT

# Same task names as the Windows path so scheduler_status returns
# unified output.  The cron marker comment uses these as suffixes.
CYCLE_TASK_NAME = "XaxiuHarnessObserverCycle"
RETRO_TASK_NAME = "XaxiuHarnessObserverDailyRetro"
CHAT_AUDIT_TASK_NAME = "XaxiuHarnessObserverChatAudit"
MARKER_PREFIX = "# HARNESS_OBSERVER:"


def _python_bin() -> str:
    """Return the python interpreter to use in cron entries.

    Prefers the project's venv (.venv/bin/python on *nix) so the
    cron-fired task uses the same env as interactive use; falls
    back to bare 'python'."""
    venv_py = _REPO_ROOT / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return "python"


def _has_crontab() -> bool:
    """Detect whether the `crontab` binary exists.  Linux + macOS
    have it; minimal Docker containers may not."""
    return shutil.which("crontab") is not None


def _read_crontab() -> str:
    """Return current crontab content; empty string if no crontab set
    or the binary is missing."""
    if not _has_crontab():
        return ""
    try:
        proc = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    # `crontab -l` returns 1 with "no crontab for <user>" when empty
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _write_crontab(content: str) -> tuple[bool, str]:
    """Replace user's crontab with *content*.  Returns (success, message)."""
    if not _has_crontab():
        return False, "crontab binary not found on this system"
    try:
        proc = subprocess.run(
            ["crontab", "-"], input=content,
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, f"crontab write failed: {exc}"
    if proc.returncode != 0:
        return False, f"crontab returned {proc.returncode}: {proc.stderr.strip()}"
    return True, "ok"


def _filter_out_harness_entries(content: str) -> list[str]:
    """Return the operator's cron lines (NOT owned by harness).

    Harness entries are identified by a marker-comment line
    `# HARNESS_OBSERVER:<task_name>` followed by the cron line.
    We drop both the marker and the next line for each.
    """
    out: list[str] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(MARKER_PREFIX):
            # Skip this marker line + the next (the cron entry)
            i += 2
            continue
        out.append(line)
        i += 1
    return out


def _make_cron_entry(task_name: str, schedule: str, command: str) -> list[str]:
    """Return the 2-line cron entry: marker + cron line."""
    return [f"{MARKER_PREFIX}{task_name}", f"{schedule} {command}"]


def register_cron_tasks(cadence_minutes: int = 60,
                         daily_time: str = "23:00",
                         include_chat: bool = True) -> tuple[bool, str]:
    """Register the observer's cron entries (Linux/Mac).

    Idempotent: existing harness-owned entries are replaced.  Operator
    cron entries (without the HARNESS_OBSERVER marker) are preserved.

    cadence_minutes: cycle cadence (uses '*/N * * * *' form when N is
                     a divisor of 60; otherwise falls back to '0 * * * *'
                     with a warning in the message)
    daily_time:      HH:MM 24h for the retro task
    """
    if not _has_crontab():
        return False, "crontab binary not found — cannot register tasks"

    py = _python_bin()
    project = _REPO_ROOT

    # Cycle schedule
    if cadence_minutes > 0 and 60 % cadence_minutes == 0 and cadence_minutes <= 60:
        cycle_schedule = f"*/{cadence_minutes} * * * *"
        schedule_note = ""
    else:
        # Non-divisor cadences would need anacron; fall back to hourly
        cycle_schedule = "0 * * * *"
        schedule_note = (
            f" (warning: cadence_minutes={cadence_minutes} not a divisor "
            f"of 60; using hourly schedule)"
        )

    cycle_cmd = (
        f'cd {project} && {py} -m harness observer cycle-now '
        f">>/tmp/harness-observer-cycle.log 2>&1"
    )

    # Daily retro schedule
    try:
        hh, mm = daily_time.split(":")
        hh_int, mm_int = int(hh), int(mm)
        if not (0 <= hh_int <= 23 and 0 <= mm_int <= 59):
            raise ValueError
        retro_schedule = f"{mm_int} {hh_int} * * *"
    except (ValueError, AttributeError):
        return False, f"invalid daily_time {daily_time!r}; expected HH:MM"

    retro_cmd = (
        f'cd {project} && {py} -m harness observer daily-retro '
        f">>/tmp/harness-observer-retro.log 2>&1"
    )

    # Build new crontab content: operator entries + harness entries
    existing = _read_crontab()
    operator_lines = _filter_out_harness_entries(existing)
    new_lines = list(operator_lines)
    new_lines.extend(_make_cron_entry(CYCLE_TASK_NAME, cycle_schedule, cycle_cmd))
    new_lines.extend(_make_cron_entry(RETRO_TASK_NAME, retro_schedule, retro_cmd))
    if include_chat:
        chat_cmd = (
            f'cd {project} && {py} -m harness observer audit-chat '
            f">>/tmp/harness-observer-chat.log 2>&1"
        )
        new_lines.extend(_make_cron_entry(
            CHAT_AUDIT_TASK_NAME, cycle_schedule, chat_cmd,
        ))

    new_content = "\n".join(new_lines).rstrip() + "\n"
    ok, msg = _write_crontab(new_content)
    if not ok:
        return False, msg

    return True, (
        f"Cron tasks registered (cycle '{cycle_schedule}', retro "
        f"'{retro_schedule}'{schedule_note})"
    )


def unregister_cron_tasks() -> tuple[bool, str]:
    """Remove all harness-owned cron entries.  Preserves operator's
    other cron entries."""
    if not _has_crontab():
        return False, "crontab binary not found"
    existing = _read_crontab()
    if not existing.strip():
        return True, "no crontab present; nothing to unregister"
    operator_lines = _filter_out_harness_entries(existing)
    new_content = "\n".join(operator_lines).rstrip() + "\n"
    ok, msg = _write_crontab(new_content)
    if not ok:
        return False, msg
    return True, "harness cron entries removed"


def scheduler_status() -> dict:
    """Return a structured status of harness-owned cron entries.

    Unified schema across the Windows + cron paths so harness
    observer scheduler-status returns the same JSON shape regardless
    of platform.

    Returns:
        {
            "platform": "cron" | "task_scheduler" | "unavailable",
            "tasks": {
                "<task_name>": {"armed": bool, "schedule": str | None},
                ...
            },
            "count_armed": int,
        }
    """
    if not _has_crontab():
        return {"platform": "unavailable",
                "tasks": {}, "count_armed": 0,
                "reason": "crontab binary not found"}
    content = _read_crontab()
    tasks: dict[str, dict] = {
        CYCLE_TASK_NAME: {"armed": False, "schedule": None},
        RETRO_TASK_NAME: {"armed": False, "schedule": None},
        CHAT_AUDIT_TASK_NAME: {"armed": False, "schedule": None},
    }
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(MARKER_PREFIX):
            task_name = line[len(MARKER_PREFIX):].strip()
            if task_name in tasks and i + 1 < len(lines):
                # Schedule is the first 5 fields of the next line
                fields = lines[i + 1].split(None, 5)
                if len(fields) >= 5:
                    schedule = " ".join(fields[:5])
                    tasks[task_name]["armed"] = True
                    tasks[task_name]["schedule"] = schedule
    return {
        "platform": "cron",
        "tasks": tasks,
        "count_armed": sum(1 for t in tasks.values() if t["armed"]),
    }


# -- platform dispatch -----------------------------------------------------


def is_unix_like() -> bool:
    """True on Linux / macOS / *BSD; False on Windows."""
    return sys.platform != "win32"
