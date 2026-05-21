"""Supervisor base class, concrete implementations, and registry dispatch."""

from __future__ import annotations

import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from harness.loops.state import LoopState


@dataclass
class SupervisorResult:
    """Return value from a single supervisor run."""

    phase: str
    state_diff: dict[str, Any] = field(default_factory=dict)
    write_set: list[str] = field(default_factory=list)
    escalation: dict[str, Any] | None = None
    log_summary: str = ""


class BaseSupervisor(ABC):
    """Abstract base for a dev-loop phase supervisor."""

    @property
    @abstractmethod
    def phase(self) -> str:
        """Canonical phase name (e.g. ``testing``)."""

    @abstractmethod
    def run(self, state: LoopState, *, project: Path, now: datetime, **kwargs: Any) -> SupervisorResult:
        """Execute the supervisor and return a diff to apply to *state*."""


class TestingSupervisor(BaseSupervisor):
    """Mechanical testing supervisor.

    Runs the pytest suite, classifies the outcome, and returns a state diff
    that updates ``phase_cursors.testing``.
    """

    @property
    def phase(self) -> str:
        return "testing"

    def run(
        self,
        state: LoopState,
        *,
        project: Path,
        now: datetime,
        tests_dir: Path | None = None,
        **kwargs: Any,
    ) -> SupervisorResult:
        tests_dir = tests_dir or (project / "tests")
        if not tests_dir.exists():
            return SupervisorResult(
                phase=self.phase,
                escalation={
                    "level": "L4",
                    "tag": "L4.testing.E_TEST_INFRA_BROKEN",
                    "diagnostic": f"tests directory not found at {tests_dir}",
                },
                log_summary="tests directory missing",
            )

        proc = subprocess.run(
            ["python", "-m", "pytest", str(tests_dir), "-q", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=str(project),
        )

        # Classification
        if proc.returncode == 0:
            outcome = "pass"
        elif proc.returncode == 1:
            outcome = "fail"
        else:
            outcome = "error"

        summary_match = re.search(r"(\d+ passed.*?)\n", proc.stdout + proc.stderr)
        summary = summary_match.group(1) if summary_match else "unknown"

        # Extract failed test names from short summary lines
        failed_tests: list[str] = []
        if outcome != "pass":
            for line in (proc.stdout + proc.stderr).splitlines():
                m = re.match(r"FAILED\s+([\w/._-]+)::", line)
                if m:
                    failed_tests.append(m.group(1))

        # Build state diff
        next_due = (now + timedelta(minutes=60)).isoformat()
        cadence = state.operator_directives.get("cadence_minutes", {})
        if isinstance(cadence, dict):
            testing_cadence = cadence.get("testing", 60)
            if isinstance(testing_cadence, (int, float)):
                next_due = (now + timedelta(minutes=testing_cadence)).isoformat()

        state_diff: dict[str, Any] = {
            "phase_cursors.testing.last_run_at": now.isoformat(),
            "phase_cursors.testing.next_due_at": next_due,
            "phase_cursors.testing.pytest_outcome": outcome,
            "phase_cursors.testing.pytest_summary": summary,
        }

        # Compare against last green tick to detect regressions
        last_outcome = (
            state.phase_cursors.get("testing", {}).get("pytest_outcome")
            if isinstance(state.phase_cursors, dict)
            else None
        )
        regressions: list[str] = []
        if outcome == "fail" and last_outcome == "pass":
            regressions = failed_tests
            state_diff["phase_cursors.testing.regressions"] = regressions
            # Append to integrating pending_merges with block_commit
            pending_merges = (
                state.phase_cursors.get("integrating", {}).get("pending_merges", [])
                if isinstance(state.phase_cursors, dict)
                else []
            )
            if not isinstance(pending_merges, list):
                pending_merges = []
            pending_merges.append(
                {
                    "block_commit": True,
                    "reason": f"L3.testing.E_REGRESSION: {regressions}",
                    "detected_at": now.isoformat(),
                }
            )
            state_diff["phase_cursors.integrating.pending_merges"] = pending_merges

        if outcome == "error":
            return SupervisorResult(
                phase=self.phase,
                state_diff=state_diff,
                write_set=["phase_cursors.testing"],
                escalation={
                    "level": "L4",
                    "tag": "L4.testing.E_TEST_INFRA_BROKEN",
                    "diagnostic": f"pytest exited {proc.returncode}: {summary}",
                },
                log_summary=f"pytest error: {summary}",
            )

        if regressions:
            return SupervisorResult(
                phase=self.phase,
                state_diff=state_diff,
                write_set=["phase_cursors.testing", "phase_cursors.integrating"],
                escalation={
                    "level": "L3",
                    "tag": "L3.testing.E_REGRESSION",
                    "diagnostic": f"New failures detected: {regressions}",
                },
                log_summary=f"regressions: {regressions}",
            )

        return SupervisorResult(
            phase=self.phase,
            state_diff=state_diff,
            write_set=["phase_cursors.testing"],
            log_summary=f"tests {outcome}: {summary}",
        )


class _NoOpSupervisor(BaseSupervisor):
    """Placeholder supervisor for phases not yet implemented."""

    def __init__(self, phase_name: str) -> None:
        self._phase = phase_name

    @property
    def phase(self) -> str:
        return self._phase

    def run(self, state: LoopState, *, project: Path, now: datetime, **kwargs: Any) -> SupervisorResult:
        return SupervisorResult(
            phase=self.phase,
            log_summary="pending Wave 6/B+",
        )


_SUPERVISORS: dict[str, BaseSupervisor] = {
    "testing": TestingSupervisor(),
    "creativity": _NoOpSupervisor("creativity"),
    "developing": _NoOpSupervisor("developing"),
    "integrating": _NoOpSupervisor("integrating"),
    "process_improvement": _NoOpSupervisor("process_improvement"),
}


def run_supervisor(
    phase: str,
    state: LoopState,
    *,
    project: Path,
    now: datetime,
    **kwargs: Any,
) -> SupervisorResult:
    """Dispatch to the registered supervisor for *phase*."""
    sup = _SUPERVISORS.get(phase)
    if sup is None:
        return SupervisorResult(
            phase=phase,
            log_summary=f"unknown phase {phase!r} — pending Wave 6/B+",
        )
    return sup.run(state, project=project, now=now, **kwargs)
