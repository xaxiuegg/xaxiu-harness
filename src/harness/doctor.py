"""harness doctor — preflight diagnostics for fresh-clone onboarding.

Each check returns a Diagnosis with severity ("ok" | "warn" | "fail") +
short message + optional fix hint.  Output is plain text, color-coded:
green ✓ for ok, yellow ⚠ for warn, red ✗ for fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Diagnosis:
    name: str
    severity: str  # ok | warn | fail
    message: str
    fix: str = ""


def _check_git() -> Diagnosis:
    if shutil.which("git") is None:
        return Diagnosis("git", "fail", "git is not on PATH",
                         "Install Git for Windows from https://git-scm.com/")
    try:
        out = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True, text=True, timeout=5,
        )
        if not out.stdout.strip():
            return Diagnosis("git", "warn", "git user.email not set",
                             "Run: git config --global user.email you@example.com")
    except Exception as exc:
        return Diagnosis("git", "warn", f"git probe failed: {exc}")
    return Diagnosis("git", "ok", "git installed + identity set")


def _check_python_version() -> Diagnosis:
    v = sys.version_info
    if v < (3, 11):
        return Diagnosis("python", "fail",
                         f"Python {v.major}.{v.minor} too old (need ≥3.11)",
                         "Install Python 3.11+ from python.org")
    return Diagnosis("python", "ok", f"Python {v.major}.{v.minor} OK")


def _check_dpapi() -> Diagnosis:
    if sys.platform != "win32":
        return Diagnosis("dpapi", "warn", "DPAPI is Windows-only — secrets store unavailable here")
    try:
        from harness.secrets import dpapi
        # Probe a non-existent secret to exercise read path
        _ = dpapi.list_secrets()
        return Diagnosis("dpapi", "ok", "DPAPI read works")
    except Exception as exc:
        return Diagnosis("dpapi", "fail", f"DPAPI unreadable: {exc}",
                         "Run `harness install` to seed the secrets store")


def _check_secrets() -> Diagnosis:
    try:
        from harness.secrets import dpapi
        names = set(dpapi.list_secrets())
    except Exception:
        return Diagnosis("secrets", "warn", "couldn't enumerate secrets")
    required_any = {"KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}
    present_dpapi = names & required_any
    present_env = {k for k in required_any if os.environ.get(k)}
    if present_dpapi or present_env:
        return Diagnosis(
            "secrets", "ok",
            f"engine keys available: dpapi={sorted(present_dpapi) or '(none)'} env={sorted(present_env) or '(none)'}",
        )
    return Diagnosis("secrets", "fail",
                     "no engine API keys found (DPAPI or env)",
                     "Run `harness install` or set DEEPSEEK_API_KEY / KIMI_API_KEY env vars")


def _check_engine_reachability() -> Diagnosis:
    required = {"KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}
    try:
        from harness.secrets import dpapi
        dpapi_count = sum(1 for s in dpapi.list_secrets() if s in required)
    except Exception:
        dpapi_count = 0
    env_hits = [k for k in required if os.environ.get(k)]
    if dpapi_count == 0 and not env_hits:
        return Diagnosis(
            "engine_reachability", "fail",
            "no engine API keys found (DPAPI or env)",
            "Run `harness install` or set DEEPSEEK_API_KEY / KIMI_API_KEY env vars",
        )
    parts = []
    if dpapi_count:
        parts.append(f"dpapi={dpapi_count}")
    if env_hits:
        parts.append(f"env={env_hits[0]}")
    return Diagnosis("engine_reachability", "ok", " ".join(parts))


def _check_env_var_inventory() -> Diagnosis:
    keys = [
        "KIMI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
    ]
    parts = []
    any_set = False
    for k in keys:
        if os.environ.get(k):
            parts.append(f"{k}:SET")
            any_set = True
        else:
            parts.append(f"{k}:UNSET")
    severity = "ok" if any_set else "warn"
    return Diagnosis(
        "env_var_inventory",
        severity,
        ", ".join(parts),
        "Set at least one engine API key in your environment",
    )


def _check_coord_writable() -> Diagnosis:
    try:
        coord = Path("coord")
        coord.mkdir(exist_ok=True)
        probe = coord / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Diagnosis("coord_dir", "ok", "coord/ is writable")
    except Exception as exc:
        return Diagnosis("coord_dir", "fail", f"can't write to coord/: {exc}",
                         "Check filesystem permissions on the project dir")


def _check_task_scheduler() -> Diagnosis:
    if sys.platform != "win32":
        return Diagnosis("task_scheduler", "warn", "Windows-only — skipped")
    if shutil.which("schtasks") is None and shutil.which("powershell") is None:
        return Diagnosis("task_scheduler", "fail", "neither schtasks nor PowerShell on PATH")
    try:
        out = subprocess.run(
            ["schtasks", "/Query", "/FO", "LIST"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return Diagnosis("task_scheduler", "warn",
                             "schtasks query failed — may need admin / scope")
        return Diagnosis("task_scheduler", "ok", "Task Scheduler reachable")
    except Exception as exc:
        return Diagnosis("task_scheduler", "warn", f"task scheduler probe error: {exc}")


def run_all() -> list[Diagnosis]:
    """Run every check and return the list of Diagnoses."""
    return [
        _check_python_version(),
        _check_git(),
        _check_dpapi(),
        _check_secrets(),
        _check_engine_reachability(),
        _check_env_var_inventory(),
        _check_coord_writable(),
        _check_task_scheduler(),
    ]


def overall_severity(diagnoses: list[Diagnosis]) -> str:
    """Return the most-severe severity across all diagnoses."""
    if any(d.severity == "fail" for d in diagnoses):
        return "fail"
    if any(d.severity == "warn" for d in diagnoses):
        return "warn"
    return "ok"
