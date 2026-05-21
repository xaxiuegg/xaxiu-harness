"""Supervisor base class, concrete implementations, and registry dispatch."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
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


# ---------------------------------------------------------------------------
# Creativity supervisor
# ---------------------------------------------------------------------------


class CreativitySupervisor(BaseSupervisor):
    """Generates improvement ideas using an external engine.

    Defaults to ``claude-in-session`` which is a no-op (needs an external
    engine like *kimi* or *deepseek* for judgment work).
    """

    @property
    def phase(self) -> str:
        return "creativity"

    def __init__(self, engine: str = "claude-in-session") -> None:
        self.engine = engine

    def run(self, state: LoopState, *, project: Path, now: datetime, **kwargs: Any) -> SupervisorResult:
        if self.engine == "claude-in-session":
            return SupervisorResult(
                phase=self.phase,
                log_summary=(
                    "CreativitySupervisor requires an external engine "
                    "(kimi/deepseek); claude-in-session is a no-op"
                ),
            )

        # Build context
        wave_plan = state.wave_plan if isinstance(state.wave_plan, list) else []
        recent_commits = self._recent_commits(project)
        parked = (
            state.phase_cursors.get("creativity", {}).get("queue", [])
            if isinstance(state.phase_cursors, dict)
            else []
        )

        prompt = self._build_prompt(wave_plan, recent_commits, parked)

        tmp_packet = project / "state" / f".tmp_creativity_{uuid.uuid4().hex}.md"
        tmp_packet.write_text(prompt, encoding="utf-8")

        try:
            from harness.engines.dispatcher import dispatch_packet

            result = dispatch_packet(
                project="xaxiu-harness",
                packet_path=str(tmp_packet),
                force_engine=self.engine,
            )
        finally:
            tmp_packet.unlink(missing_ok=True)

        if not result.success or not result.text.strip():
            return SupervisorResult(
                phase=self.phase,
                escalation={
                    "level": "L3",
                    "tag": "L3.creativity.E_ENGINE_FAILURE",
                    "diagnostic": f"Engine dispatch failed: {result.error}",
                },
                log_summary=f"engine failure: {result.error}",
            )

        ideas = self._parse_ideas(result.text)
        if not ideas:
            return SupervisorResult(
                phase=self.phase,
                log_summary="no valid ideas parsed from engine response",
            )

        top = max(ideas, key=lambda x: x.get("strategic_score", 0))
        score = top.get("strategic_score", 0)
        if score < 60:
            return SupervisorResult(
                phase=self.phase,
                log_summary=f"top idea score {score} below threshold 60",
            )

        queue = list(parked)
        queue.append(top)
        next_due = (now + timedelta(hours=6)).isoformat()

        return SupervisorResult(
            phase=self.phase,
            state_diff={
                "phase_cursors.creativity.last_run_at": now.isoformat(),
                "phase_cursors.creativity.next_due_at": next_due,
                "phase_cursors.creativity.queue": queue,
            },
            write_set=["phase_cursors.creativity"],
            log_summary=f"queued idea {top.get('id')} with score {score}",
        )

    def _recent_commits(self, project: Path) -> list[str]:
        try:
            proc = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                capture_output=True,
                text=True,
                cwd=str(project),
                check=False,
            )
            return [line for line in proc.stdout.splitlines() if line]
        except Exception:
            return []

    def _build_prompt(self, wave_plan: list[Any], recent_commits: list[str], parked: list[Any]) -> str:
        parked_ids = {i.get("id") for i in parked if isinstance(i, dict)}
        wp_summary = (
            "\n".join(
                f"- {getattr(w, 'id', '?')}: {getattr(w, 'name', '?')} ({getattr(w, 'status', '?')})"
                for w in wave_plan
            )
            if wave_plan
            else "(empty)"
        )
        commits_summary = "\n".join(f"- {c}" for c in recent_commits) if recent_commits else "(none)"

        return (
            f"# Creativity Audit\n\n"
            f"## Current wave plan\n{wp_summary}\n\n"
            f"## Recent commits\n{commits_summary}\n\n"
            f"## Already queued ideas\n"
            f"{chr(10).join(f'- {pid}' for pid in parked_ids) if parked_ids else '(none)'}\n\n"
            f"Generate 1-3 improvement ideas for the xaxiu-harness project. "
            f"Avoid duplicates of already-queued ideas.\n\n"
            f"Respond with strict JSON only:\n"
            f"```json\n[\n"
            f"  {{\n"
            f'    "id": "idea-YYYYMMDD-slug",\n'
            f'    "title": "...",\n'
            f'    "description": "...",\n'
            f'    "strategic_score": 0-100,\n'
            f'    "operator_alignment_score": 0-100,\n'
            f'    "estimated_loc": int,\n'
            f'    "estimated_kimi_minutes": int,\n'
            f'    "risk": "low|med|high"\n'
            f"  }}\n"
            f"]\n```\n"
        )

    def _parse_ideas(self, text: str) -> list[dict[str, Any]]:
        m = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1)
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [i for i in data if isinstance(i, dict)]
        except json.JSONDecodeError:
            pass
        return []


# ---------------------------------------------------------------------------
# Developing supervisor
# ---------------------------------------------------------------------------


class DevelopingSupervisor(BaseSupervisor):
    """Picks the next eligible wave and dispatches it via xaxiu-swarm."""

    @property
    def phase(self) -> str:
        return "developing"

    def run(self, state: LoopState, *, project: Path, now: datetime, **kwargs: Any) -> SupervisorResult:
        active = state.active_dispatches if isinstance(state.active_dispatches, list) else []
        for d in active:
            if getattr(d, "phase", None) == "developing":
                return SupervisorResult(
                    phase=self.phase,
                    log_summary="developing dispatch already in flight",
                )

        wave_plan = state.wave_plan if isinstance(state.wave_plan, list) else []
        done_ids = {
            w.id for w in wave_plan
            if getattr(w, "status", None) == "done"
        }

        eligible: list[Any] = []
        for w in wave_plan:
            if getattr(w, "status", None) != "queued":
                continue
            deps = getattr(w, "depends_on", []) or []
            if all(d in done_ids for d in deps):
                eligible.append(w)

        if not eligible:
            return SupervisorResult(
                phase=self.phase,
                log_summary="no eligible waves to develop",
            )

        wave = eligible[0]
        wave_id = getattr(wave, "id", "")

        # Look for existing packet
        packets_dir = project / "coord" / "packets"
        packet_file: Path | None = None
        if packets_dir.exists():
            for entry in packets_dir.iterdir():
                if entry.is_dir() and entry.name.startswith(wave_id):
                    candidate = entry / "packet.md"
                    if candidate.exists():
                        packet_file = candidate
                        break

        if packet_file is None:
            return SupervisorResult(
                phase=self.phase,
                log_summary=f"no packet found for wave {wave_id}; needs Wave 6/D drafting",
            )

        task_id = uuid.uuid4().hex
        cmd = [
            "xaxiu-swarm",
            "dispatch",
            "--backend", "kimi",
            "--deliverable", str(project),
            "--add-dir", str(project),
            "--context-file", str(project / "CLAUDE.md"),
            "--progress", "30",
            "--timeout", "420",
            str(packet_file),
        ]

        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(project),
            )
        except FileNotFoundError:
            return SupervisorResult(
                phase=self.phase,
                escalation={
                    "level": "L4",
                    "tag": "L4.dispatch.E_SWARM_NOT_FOUND",
                    "diagnostic": "xaxiu-swarm executable not found in PATH",
                },
                log_summary="xaxiu-swarm not found",
            )

        new_dispatch = {
            "task_id": task_id,
            "packet": str(packet_file),
            "engine": "kimi",
            "dispatched_at": now.isoformat(),
            "phase": "developing",
            "wave_id": wave_id,
        }

        updated_dispatches = list(active)
        updated_dispatches.append(new_dispatch)

        updated_plan: list[dict[str, Any]] = []
        for w in wave_plan:
            w_data = w.model_dump(mode="json") if hasattr(w, "model_dump") else dict(w)
            if w_data.get("id") == wave_id:
                w_data["status"] = "in_progress"
            updated_plan.append(w_data)

        return SupervisorResult(
            phase=self.phase,
            state_diff={
                "active_dispatches": updated_dispatches,
                "wave_plan": updated_plan,
            },
            write_set=["active_dispatches", "wave_plan"],
            log_summary=f"dispatched wave {wave_id} via xaxiu-swarm (task {task_id})",
        )


# ---------------------------------------------------------------------------
# Integrating supervisor
# ---------------------------------------------------------------------------


class IntegratingSupervisor(BaseSupervisor):
    """Validates pending merges, runs tests, and optionally commits."""

    @property
    def phase(self) -> str:
        return "integrating"

    def run(self, state: LoopState, *, project: Path, now: datetime, **kwargs: Any) -> SupervisorResult:
        pending_merges = (
            state.phase_cursors.get("integrating", {}).get("pending_merges", [])
            if isinstance(state.phase_cursors, dict)
            else []
        )
        if not isinstance(pending_merges, list):
            pending_merges = []

        if not pending_merges:
            return SupervisorResult(
                phase=self.phase,
                log_summary="no pending merges",
            )

        wave_plan = state.wave_plan if isinstance(state.wave_plan, list) else []
        allow_auto_commit = os.environ.get("HARNESS_ALLOW_AUTO_COMMIT", "false").lower() == "true"

        updated_plan: list[dict[str, Any]] | None = None
        updated_merges: list[dict[str, Any]] = []
        committed_wave_ids: list[str] = []

        for entry in pending_merges:
            if not isinstance(entry, dict):
                continue
            if entry.get("block_commit"):
                updated_merges.append(entry)
                continue

            output_file = entry.get("output_file")
            if output_file and Path(output_file).exists():
                proc = subprocess.run(
                    ["python", str(project / "bin" / "parse-swarm-status.py"), str(output_file)],
                    capture_output=True,
                    text=True,
                    cwd=str(project),
                    check=False,
                )
                parse_ok = proc.returncode == 0
            else:
                parse_ok = True  # Nothing to parse

            # git diff --stat
            diff_proc = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True,
                text=True,
                cwd=str(project),
                check=False,
            )
            has_changes = bool(diff_proc.stdout.strip())

            # pytest
            pytest_proc = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-q"],
                capture_output=True,
                text=True,
                cwd=str(project),
                check=False,
            )
            tests_ok = pytest_proc.returncode == 0

            if not parse_ok or not tests_ok:
                updated_merges.append(entry)
                continue

            if has_changes and allow_auto_commit:
                subprocess.run(
                    ["git", "add", "."],
                    cwd=str(project),
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(
                    ["git", "commit", "-m", f"feat: integrate wave {entry.get('wave_id', '?')}"],
                    cwd=str(project),
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(
                    ["git", "push"],
                    cwd=str(project),
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # Mark wave done
            wave_id = entry.get("wave_id")
            if wave_id is not None:
                committed_wave_ids.append(wave_id)
                if updated_plan is None:
                    updated_plan = [
                        w.model_dump(mode="json") if hasattr(w, "model_dump") else dict(w)
                        for w in wave_plan
                    ]
                for w in updated_plan:
                    if w.get("id") == wave_id:
                        w["status"] = "done"
                        w["completed_at"] = now.isoformat()

        state_diff: dict[str, Any] = {}
        if updated_plan is not None:
            state_diff["wave_plan"] = updated_plan
        if updated_merges != pending_merges:
            state_diff["phase_cursors.integrating.pending_merges"] = updated_merges

        if not state_diff:
            return SupervisorResult(
                phase=self.phase,
                log_summary="no merges processed (all blocked or failed validation)",
            )

        return SupervisorResult(
            phase=self.phase,
            state_diff=state_diff,
            write_set=["wave_plan", "phase_cursors.integrating"],
            log_summary=f"integrated waves {committed_wave_ids}",
        )


# ---------------------------------------------------------------------------
# Process improvement supervisor
# ---------------------------------------------------------------------------


class ProcessImprovementSupervisor(BaseSupervisor):
    """Reads logs + git history, dispatches audit prompt, and applies findings.

    Defaults to ``claude-in-session`` which is a no-op (needs an external
    engine like *kimi* or *deepseek* for judgment work).
    """

    @property
    def phase(self) -> str:
        return "process_improvement"

    def __init__(self, engine: str = "claude-in-session") -> None:
        self.engine = engine

    def run(self, state: LoopState, *, project: Path, now: datetime, **kwargs: Any) -> SupervisorResult:
        if self.engine == "claude-in-session":
            return SupervisorResult(
                phase=self.phase,
                log_summary=(
                    "ProcessImprovementSupervisor requires an external engine "
                    "(kimi/deepseek); claude-in-session is a no-op"
                ),
            )

        from harness.state import jsonl_log

        log_entries = jsonl_log.read_recent_entries(limit=30)
        recent_commits = self._recent_commits(project)

        prompt = self._build_prompt(log_entries, recent_commits)

        tmp_packet = project / "state" / f".tmp_process_improvement_{uuid.uuid4().hex}.md"
        tmp_packet.write_text(prompt, encoding="utf-8")

        try:
            from harness.engines.dispatcher import dispatch_packet

            result = dispatch_packet(
                project="xaxiu-harness",
                packet_path=str(tmp_packet),
                force_engine=self.engine,
            )
        finally:
            tmp_packet.unlink(missing_ok=True)

        if not result.success or not result.text.strip():
            return SupervisorResult(
                phase=self.phase,
                escalation={
                    "level": "L3",
                    "tag": "L3.process_improvement.E_ENGINE_FAILURE",
                    "diagnostic": f"Engine dispatch failed: {result.error}",
                },
                log_summary=f"engine failure: {result.error}",
            )

        findings = self._parse_findings(result.text)
        if not findings:
            return SupervisorResult(
                phase=self.phase,
                log_summary="no valid findings parsed from engine response",
            )

        p1_findings = [f for f in findings if f.get("tier") == "P1"]
        p3_findings = [f for f in findings if f.get("tier") == "P3"]

        applied_count = 0
        for finding in p1_findings:
            patch = finding.get("patch")
            if isinstance(patch, dict):
                file_path = project / patch.get("file", "")
                find_text = patch.get("find")
                replace_text = patch.get("replace")
                if file_path.exists() and find_text is not None:
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        if find_text in content:
                            new_content = content.replace(find_text, replace_text, 1)
                            file_path.write_text(new_content, encoding="utf-8")
                            applied_count += 1
                    except Exception:
                        pass

        findings_log = (
            state.phase_cursors.get("process_improvement", {}).get("findings_log", [])
            if isinstance(state.phase_cursors, dict)
            else []
        )
        if not isinstance(findings_log, list):
            findings_log = []
        for f in p3_findings:
            findings_log.append({
                "id": f.get("id", ""),
                "title": f.get("title", ""),
                "rationale": f.get("rationale", ""),
                "logged_at": now.isoformat(),
            })

        next_due = (now + timedelta(hours=12)).isoformat()

        return SupervisorResult(
            phase=self.phase,
            state_diff={
                "phase_cursors.process_improvement.last_run_at": now.isoformat(),
                "phase_cursors.process_improvement.next_due_at": next_due,
                "phase_cursors.process_improvement.findings_log": findings_log,
            },
            write_set=["phase_cursors.process_improvement"],
            log_summary=(
                f"applied {applied_count} P1 patches, "
                f"logged {len(p3_findings)} P3 findings"
            ),
        )

    def _recent_commits(self, project: Path) -> list[str]:
        try:
            proc = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                capture_output=True,
                text=True,
                cwd=str(project),
                check=False,
            )
            return [line for line in proc.stdout.splitlines() if line]
        except Exception:
            return []

    def _build_prompt(self, log_entries: list[dict], recent_commits: list[str]) -> str:
        log_summary = (
            "\n".join(
                f"- {e.get('backend', '?')} | {e.get('outcome', '?')} | {e.get('latency_ms', '?')}ms"
                for e in log_entries
            )
            if log_entries
            else "(no log entries)"
        )
        commits_summary = "\n".join(f"- {c}" for c in recent_commits) if recent_commits else "(none)"

        return (
            f"# Process Improvement Audit\n\n"
            f"## Recent engine log entries\n{log_summary}\n\n"
            f"## Recent commits\n{commits_summary}\n\n"
            f"Identify 1-5 process improvement findings for the xaxiu-harness dev loop.\n\n"
            f"Classify each as:\n"
            f"- P1 = quick fix (small text patch)\n"
            f"- P2 = requires a packet / wave plan\n"
            f"- P3 = memory / long-term observation\n\n"
            f"Respond with strict JSON only:\n"
            f"```json\n[\n"
            f"  {{\n"
            f'    "id": "pi-YYYYMMDD-slug",\n'
            f'    "tier": "P1|P2|P3",\n'
            f'    "title": "...",\n'
            f'    "rationale": "...",\n'
            f'    "evidence": ["..."],\n'
            f'    "proposed_action": "...",\n'
            f'    "patch": {{\n'
            f'      "file": "relative/path",\n'
            f'      "find": "text to find",\n'
            f'      "replace": "replacement"\n'
            f'    }}\n'
            f"  }}\n"
            f"]\n```\n"
        )

    def _parse_findings(self, text: str) -> list[dict[str, Any]]:
        m = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1)
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [i for i in data if isinstance(i, dict)]
        except json.JSONDecodeError:
            pass
        return []


# ---------------------------------------------------------------------------
# No-op fallback
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_SUPERVISORS: dict[str, BaseSupervisor] = {
    "testing": TestingSupervisor(),
    "creativity": CreativitySupervisor(),
    "developing": DevelopingSupervisor(),
    "integrating": IntegratingSupervisor(),
    "process_improvement": ProcessImprovementSupervisor(),
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
