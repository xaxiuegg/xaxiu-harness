"""Integrator: aggregates worker results and optionally commits/pushes."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness.coord.run_state import read_run_state, write_run_state
from harness.coord.schemas import IntegratorStatus, RunState, RunStateLiteral


@dataclass
class IntegrationReport:
    success: bool
    commit_sha: str | None = None
    pushed: bool = False
    test_summary: dict[str, int] | None = None
    diagnostic: str = ""


def _git(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a git subcommand and return (rc, stdout, stderr)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def integrate(
    run_dir: Path,
    *,
    project_root: Path | None = None,
    auto_commit: bool = False,
    auto_push: bool = False,
) -> IntegrationReport:
    """Integrate a completed run: run tests, optionally commit + push."""
    run_dir = Path(run_dir)
    state = read_run_state(run_dir / "run_state.json")
    if state is None:
        return IntegrationReport(success=False, diagnostic="No run_state found")

    pr = project_root or Path.cwd()

    # Run pytest and collect summary
    test_summary: dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "-q", "--tb=no"],
            cwd=pr,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        # Parse summary line like "2 passed, 1 failed, 3 skipped in 0.01s"
        for line in proc.stdout.splitlines():
            if "passed" in line or "failed" in line or "error" in line or "skipped" in line:
                parts = line.replace(" in ", " ").replace(",", "").split()
                for i, word in enumerate(parts):
                    if word == "passed":
                        try:
                            test_summary["passed"] = int(parts[i - 1])
                        except (IndexError, ValueError):
                            pass
                    elif word == "failed":
                        try:
                            test_summary["failed"] = int(parts[i - 1])
                        except (IndexError, ValueError):
                            pass
                    elif word.startswith("error"):
                        try:
                            test_summary["errors"] = int(parts[i - 1])
                        except (IndexError, ValueError):
                            pass
                    elif word == "skipped":
                        try:
                            test_summary["skipped"] = int(parts[i - 1])
                        except (IndexError, ValueError):
                            pass
                break
    except Exception as exc:
        return IntegrationReport(success=False, diagnostic=f"pytest failed: {exc}")

    # Env gate check
    allow_env = os.environ.get("HARNESS_ALLOW_AUTO_INTEGRATE", "").lower()
    if auto_commit and allow_env == "true":
        rc, out, err = _git("add", "-A", cwd=pr)
        if rc != 0:
            return IntegrationReport(success=False, diagnostic=f"git add failed: {err}")
        rc, out, err = _git(
            "commit",
            "-m",
            f"feat(coord): integrate run {state.run_id}",
            cwd=pr,
        )
        if rc != 0 and "nothing to commit" not in (out + err).lower():
            return IntegrationReport(success=False, diagnostic=f"git commit failed: {err}")
        sha = out.strip().splitlines()[-1] if out else None
        pushed = False
        if auto_push and sha:
            rc_push, _, err_push = _git("push", cwd=pr)
            pushed = rc_push == 0
            if rc_push != 0:
                return IntegrationReport(
                    success=False,
                    commit_sha=sha,
                    pushed=False,
                    test_summary=test_summary,
                    diagnostic=f"git push failed: {err_push}",
                )
        state.state = RunStateLiteral.COMPLETED
        state.integrator_status = IntegratorStatus(
            state="done",
            last_action="commit+push" if pushed else "commit",
            commit_sha=sha,
        )
        write_run_state(run_dir / "run_state.json", state)
        return IntegrationReport(
            success=True,
            commit_sha=sha,
            pushed=pushed,
            test_summary=test_summary,
        )

    # No auto-commit or gate not set
    state.state = RunStateLiteral.COMPLETED
    state.integrator_status = IntegratorStatus(
        state="done",
        last_action="dry_run",
    )
    write_run_state(run_dir / "run_state.json", state)
    return IntegrationReport(
        success=test_summary.get("failed", 0) == 0 and test_summary.get("errors", 0) == 0,
        test_summary=test_summary,
        diagnostic="" if test_summary.get("failed", 0) == 0 else "Tests failed",
    )
