"""Observer cycle runner: gather context, dispatch audit, parse flags, write report.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from harness._constants import _REPO_ROOT
from harness.errors import HarnessError
from harness.engines.dispatcher import DispatchResult, dispatch_packet
from harness.observer.audit_prompt import build_audit_prompt
from harness.observer.flags import Flag, FlagSeverity, ensure_flag_dirs, write_pending_flags, _next_flag_id
from harness.state.jsonl_log import read_recent_entries as _read_log_entries
from harness.status import read_status

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CycleReport:
    cycle_id: str
    started_at: str
    ended_at: str
    engine_used: str
    audit_window_minutes: int
    prompt_size_chars: int
    response_size_chars: int
    findings_count: int
    flags_raised: list[Flag]
    report_path: Path | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Cycle runner
# ---------------------------------------------------------------------------

DEFAULT_OBSERVER_DIR: Path = _REPO_ROOT / "coord" / "observer"


def run_cycle(
    engine: str = "swarm/deepseek",
    audit_window_minutes: int = 60,
    *,
    observer_dir: Path | None = None,
    dispatch_fn: Callable[..., DispatchResult] | None = None,
    dry_run: bool = False,
) -> CycleReport:
    """Run one observer audit cycle.

    Parameters
    ----------
    engine :
        Target engine for the audit dispatch (default ``swarm/deepseek``).
    audit_window_minutes :
        Minutes of log history to include.
    observer_dir :
        Override observer output directory (for tests).
    dispatch_fn :
        Injectable ``dispatch_packet`` replacement (for tests).

    Returns
    -------
    CycleReport
    """
    base = observer_dir or DEFAULT_OBSERVER_DIR
    ensure_flag_dirs(base)

    started_at = datetime.now(timezone.utc)
    cycle_id = started_at.strftime("%Y-%m-%dT%H%M%SZ")
    started_iso = started_at.isoformat()

    # 1. Gather context
    try:
        recent_log = _read_log_entries(limit=50)
    except Exception:
        recent_log = []

    try:
        status_rows = read_status(_REPO_ROOT / "coord" / "STATUS.csv")
    except Exception:
        status_rows = []

    try:
        git_log = _recent_git_commits()
    except Exception:
        git_log = []

    prompt = build_audit_prompt(
        recent_log=recent_log,
        status_rows=status_rows,
        git_log=git_log,
        cycle_id=cycle_id,
        audit_window_minutes=audit_window_minutes,
    )

    # Dry-run: write preview JSON and return without dispatching
    if dry_run:
        output_path = str(base / "cycles" / f"cycle_report_{cycle_id}.json")
        # Compact UTC stamp (no colons) — Windows-safe filename
        stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        dryrun_path = base / f"cycle_dryrun_{stamp}.json"
        preview = {
            "prompt_first_200_chars": prompt[:200],
            "prompt_length_chars": len(prompt),
            "engine": engine,
            "output_path": output_path,
            "recent_event_count": len(recent_log),
        }
        dryrun_path.write_text(json.dumps(preview, indent=2), encoding="utf-8")
        return CycleReport(
            cycle_id=cycle_id,
            started_at=started_iso,
            ended_at=started_iso,
            engine_used=engine,
            audit_window_minutes=audit_window_minutes,
            prompt_size_chars=len(prompt),
            response_size_chars=0,
            findings_count=0,
            flags_raised=[],
            report_path=dryrun_path,
        )

    # 2. Dispatch audit
    dispatcher = dispatch_fn or dispatch_packet
    # Write prompt to a temp packet so dispatcher can route it
    packet_dir = base / "cycles" / f"audit_packet_{cycle_id}"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / "packet.md"
    packet_path.write_text(prompt, encoding="utf-8")

    result: DispatchResult = dispatcher(
        project="observer",
        packet_path=str(packet_path),
        force_engine=engine,
        force_model=None,
        wave_id=cycle_id,
    )

    ended_at = datetime.now(timezone.utc)

    # 3. Parse response
    raw_text = result.text or ""
    findings: list[dict] = []
    if raw_text:
        findings = _parse_json_array(raw_text)

    # 4. Build Flag objects
    flags: list[Flag] = []
    for fdict in findings:
        try:
            sev = FlagSeverity((fdict.get("severity", "low")).lower())
        except ValueError:
            sev = FlagSeverity.LOW

        evidence = fdict.get("evidence", [])
        if isinstance(evidence, str):
            evidence = [evidence]

        flag = Flag(
            id=_next_flag_id(base),
            severity=sev,
            category=fdict.get("category", "unknown"),
            summary=fdict.get("summary", ""),
            detail=fdict.get("detail", ""),
            evidence=evidence,
            raised_at=started_iso,
            cycle_id=cycle_id,
        )
        flags.append(flag)

    # 5. Write HIGH / CRITICAL pending files
    write_pending_flags(flags, base)

    # 6. Write cycle report
    report_path = base / "cycles" / f"cycle_report_{cycle_id}.json"
    report = {
        "cycle_id": cycle_id,
        "started_at": started_iso,
        "ended_at": ended_at.isoformat(),
        "engine_used": result.engine_used,
        "audit_window_minutes": audit_window_minutes,
        "prompt_size_chars": len(prompt),
        "response_size_chars": len(raw_text),
        "findings_count": len(findings),
        "flags_raised": [f.model_dump(mode="json") for f in flags],
        "dispatch_success": result.success,
        "dispatch_error": result.error,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return CycleReport(
        cycle_id=cycle_id,
        started_at=started_iso,
        ended_at=ended_at.isoformat(),
        engine_used=result.engine_used,
        audit_window_minutes=audit_window_minutes,
        prompt_size_chars=len(prompt),
        response_size_chars=len(raw_text),
        findings_count=len(findings),
        flags_raised=flags,
        report_path=report_path,
        error=result.error,
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_JSON_ARRAY_RE = re.compile(r"(\[.*\])", re.DOTALL)


def _parse_json_array(text: str) -> list[dict]:
    """Extract a JSON array from engine response text."""
    # Strip markdown fences
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    # Try to find an array
    m = _JSON_ARRAY_RE.search(cleaned)
    if m:
        cleaned = m.group(1)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass
    return []


def _recent_git_commits(n: int = 20) -> list[str]:
    """Return the last *n* commit subjects, newest first."""
    result = subprocess.run(
        ["git", "log", f"--max-count={n}", "--pretty=format:%s"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
