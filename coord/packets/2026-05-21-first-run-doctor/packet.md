# FIRST-RUN-DOCTOR — `harness doctor` single-command preflight

## Goal

Non-technical operator clones the repo onto a fresh machine.  Today they
hit cryptic errors (no API keys, no Task Scheduler perms, missing git
identity, …) and don't know which to fix first.  `harness doctor` runs a
traffic-light series of checks and tells them in plain English.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/doctor.py`

```python
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
```

### 2. CLI verb — TOP LEVEL (not under any group)

In `src/harness/cli.py`, find another top-level command (e.g.
`@cli.command(name="lint-spec")` which was added earlier).  Add a NEW
top-level command:

```python
@cli.command(name="doctor")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty")
def doctor_cmd(fmt: str) -> None:
    """Preflight: check git, python, DPAPI, secrets, coord/ perms, Task Scheduler."""
    import dataclasses
    from harness.doctor import run_all, overall_severity

    diagnoses = run_all()
    overall = overall_severity(diagnoses)

    if fmt == "json":
        click.echo(json.dumps({
            "overall": overall,
            "checks": [dataclasses.asdict(d) for d in diagnoses],
        }, indent=2))
    else:
        glyph = {"ok": "[OK]", "warn": "[!]", "fail": "[X]"}
        click.echo("harness doctor — preflight diagnostics")
        click.echo("=" * 50)
        for d in diagnoses:
            click.echo(f"  {glyph.get(d.severity, '?')} {d.name:<16} {d.message}")
            if d.fix:
                click.echo(f"          fix: {d.fix}")
        click.echo("=" * 50)
        click.echo(f"overall: {overall.upper()}")

    sys.exit(0 if overall != "fail" else 1)
```

### 3. Tests

`tests/test_doctor.py`:

```python
"""Tests for FIRST-RUN-DOCTOR."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.doctor import (
    Diagnosis, overall_severity, run_all,
    _check_python_version, _check_coord_writable, _check_secrets,
)


def test_python_check_passes_on_current_interpreter() -> None:
    d = _check_python_version()
    assert d.severity == "ok"


def test_coord_writable_creates_probe_then_cleans_up(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    d = _check_coord_writable()
    assert d.severity == "ok"
    # Probe file should be gone
    assert not (tmp_path / "coord" / ".doctor_probe").exists()


def test_overall_severity_picks_worst() -> None:
    diags = [
        Diagnosis("a", "ok", "fine"),
        Diagnosis("b", "warn", "meh"),
    ]
    assert overall_severity(diags) == "warn"
    diags.append(Diagnosis("c", "fail", "broken"))
    assert overall_severity(diags) == "fail"


def test_run_all_returns_list_of_diagnoses() -> None:
    diags = run_all()
    assert all(isinstance(d, Diagnosis) for d in diags)
    assert len(diags) >= 5
    names = {d.name for d in diags}
    assert {"python", "git", "secrets", "coord_dir"} <= names


def test_secrets_check_reports_when_env_var_present(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    with patch("harness.secrets.dpapi.list_secrets", return_value=[]):
        d = _check_secrets()
    assert d.severity == "ok"


def test_cli_doctor_runs(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with patch("harness.doctor.run_all", return_value=[
        Diagnosis("python", "ok", "fine"),
        Diagnosis("git", "ok", "fine"),
    ]):
        result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "overall: OK" in result.output


def test_cli_doctor_exits_1_on_fail(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with patch("harness.doctor.run_all", return_value=[
        Diagnosis("dpapi", "fail", "broken", fix="run harness install"),
    ]):
        result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 1
    assert "fix: run harness install" in result.output


def test_cli_doctor_json_format(tmp_path, monkeypatch) -> None:
    import json
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    with patch("harness.doctor.run_all", return_value=[
        Diagnosis("python", "ok", "fine"),
    ]):
        result = runner.invoke(cli, ["doctor", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["overall"] == "ok"
    assert data["checks"][0]["name"] == "python"
```

## Acceptance

- `python -m pytest tests/test_doctor.py` — green.
- Full suite stays green.
- `harness doctor` prints a traffic-light table; `harness doctor --format json` is parseable.

## Constraints

- DO NOT modify any other module.
- Stdlib + harness internals only.
- Keep doctor.py under 200 LOC.
- DO NOT block on slow checks (>5s timeout each).

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
