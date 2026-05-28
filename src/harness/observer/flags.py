"""Flag severity enum, Pydantic model, and file-system helpers.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness._constants import _REPO_ROOT

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DEFAULT_OBSERVER_DIR: Path = _REPO_ROOT / "coord" / "observer"


# ---------------------------------------------------------------------------
# Severity & model
# ---------------------------------------------------------------------------

class FlagSeverity(StrEnum):
    LOW = "low"
    MED = "med"
    HIGH = "high"
    CRITICAL = "critical"


class Flag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^FLAG-\d{4}-\d{2}-\d{2}-\d+$")
    severity: FlagSeverity
    category: str
    summary: str
    detail: str
    evidence: list[str]
    raised_at: str
    cycle_id: str
    acknowledged: bool = False
    acknowledged_at: str | None = None
    acknowledged_by: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FLAG_ID_RE = re.compile(r"^FLAG-\d{4}-\d{2}-\d{2}-(\d+)$")


def ensure_flag_dirs(observer_dir: Path | None = None) -> Path:
    """Create the observer directory tree if missing."""
    base = observer_dir or DEFAULT_OBSERVER_DIR
    for sub in ("cycles", "cycles/handled", "daily", "flags"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def _next_flag_id(observer_dir: Path | None = None) -> str:
    """Generate the next sequential flag ID for today."""
    base = observer_dir or DEFAULT_OBSERVER_DIR
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = f"FLAG-{today}-"
    existing: list[int] = []
    for subdir in (base / "flags", base / "cycles" / "handled"):
        if not subdir.exists():
            continue
        for p in subdir.glob(f"{prefix}*"):
            m = _FLAG_ID_RE.match(p.name)
            if m:
                existing.append(int(m.group(1)))
    seq = max(existing, default=0) + 1
    return f"{prefix}{seq}"


def _pending_path(severity: FlagSeverity, observer_dir: Path | None = None) -> Path:
    base = observer_dir or DEFAULT_OBSERVER_DIR
    name = f"{severity.upper()}_FLAG_PENDING.md"
    return base / name


def write_pending_flags(
    flags: list[Flag],
    observer_dir: Path | None = None,
) -> list[Path]:
    """Write MED, HIGH, and CRITICAL flags to their pending files.

    Returns the paths of files that were written or updated.

    W14-BUDGET-METER-PER-ENGINE 2026-05-28: MED was added to the
    pending-writer set so MED-severity alerts (e.g. budget-cap-alert
    at 80% spend) are visible to the operator instead of being
    silently lost.  HIGH/CRITICAL retain their interrupt-priority
    semantics; MED is "look when convenient."  LOW is still suppressed
    (intentional noise floor).
    """
    base = observer_dir or DEFAULT_OBSERVER_DIR
    written: list[Path] = []
    by_severity: dict[FlagSeverity, list[Flag]] = {
        FlagSeverity.MED: [],
        FlagSeverity.HIGH: [],
        FlagSeverity.CRITICAL: [],
    }
    for f in flags:
        if f.severity in by_severity:
            by_severity[f.severity].append(f)

    for severity, items in by_severity.items():
        if not items:
            continue
        path = _pending_path(severity, base)
        _append_flags_to_md(path, items)
        written.append(path)
    return written


def _append_flags_to_md(path: Path, flags: list[Flag]) -> None:
    """Append flags as a markdown document with embedded JSON blocks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.exists():
        lines.append("\n---\n")
    for f in flags:
        lines.append(f"## {f.id} — {f.severity.upper()} ({f.category})\n")
        lines.append("```json")
        lines.append(json.dumps(f.model_dump(mode="json"), indent=2))
        lines.append("```\n")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def list_pending_flags(
    observer_dir: Path | None = None,
) -> dict[FlagSeverity, list[Flag]]:
    """Read all pending flags from HIGH_FLAG_PENDING.md and CRITICAL_FLAG_PENDING.md."""
    base = observer_dir or DEFAULT_OBSERVER_DIR
    result: dict[FlagSeverity, list[Flag]] = {
        FlagSeverity.HIGH: [],
        FlagSeverity.CRITICAL: [],
    }
    for severity in (FlagSeverity.HIGH, FlagSeverity.CRITICAL):
        path = _pending_path(severity, base)
        if path.exists():
            result[severity] = _parse_flags_from_md(path)
    return result


def _parse_flags_from_md(path: Path) -> list[Flag]:
    """Naïve markdown parser that extracts Flag JSON headers.

    Tries to find JSON code blocks first, then falls back to regex extraction.
    """
    text = path.read_text(encoding="utf-8")
    flags: list[Flag] = []

    # Strategy 1: JSON code blocks
    for block in re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL):
        try:
            raw = json.loads(block)
            if isinstance(raw, list):
                for item in raw:
                    flags.append(Flag.model_validate(item))
            elif isinstance(raw, dict):
                flags.append(Flag.model_validate(raw))
        except (json.JSONDecodeError, ValidationError):
            pass

    # Strategy 2: if no JSON blocks, look for inline header lines
    if not flags:
        for m in re.finditer(r"^##\s+(FLAG-\S+)\s+—\s+(\w+)\s+\(([^)]+)\)", text, re.MULTILINE):
            flag_id = m.group(1)
            sev_str = m.group(2).lower()
            category = m.group(3)
            # Find the next section or end of file
            start = m.start()
            next_header = re.search(r"^##\s+", text[start + 1 :], re.MULTILINE)
            end = start + 1 + next_header.start() if next_header else len(text)
            section = text[start:end]
            summary_match = re.search(r"\*\*Summary:\*\*\s*(.+)", section)
            summary = summary_match.group(1).strip() if summary_match else ""
            raised_match = re.search(r"\*\*Raised:\*\*\s*(\S+)", section)
            raised_at = raised_match.group(1).strip() if raised_match else ""
            cycle_match = re.search(r"\*\*Cycle:\*\*\s*(\S+)", section)
            cycle_id = cycle_match.group(1).strip() if cycle_match else ""
            try:
                flags.append(
                    Flag(
                        id=flag_id,
                        severity=FlagSeverity(sev_str),
                        category=category,
                        summary=summary,
                        detail=section.strip(),
                        evidence=[],
                        raised_at=raised_at,
                        cycle_id=cycle_id,
                    )
                )
            except (ValueError, ValidationError):
                pass

    return flags


def ack_flag(
    flag_id: str,
    acknowledged_by: str = "operator",
    observer_dir: Path | None = None,
) -> Flag | None:
    """Acknowledge a flag by ID.

    Looks in pending files, marks it acknowledged, and rewrites the file.
    Returns the updated Flag or None if not found.
    """
    base = observer_dir or DEFAULT_OBSERVER_DIR
    now = datetime.now(timezone.utc).isoformat()
    for severity in (FlagSeverity.HIGH, FlagSeverity.CRITICAL):
        path = _pending_path(severity, base)
        if not path.exists():
            continue
        flags = _parse_flags_from_md(path)
        updated = False
        for f in flags:
            if f.id == flag_id:
                f.acknowledged = True
                f.acknowledged_at = now
                f.acknowledged_by = acknowledged_by
                updated = True
                break
        if updated:
            # Rewrite the file with updated flags
            path.write_text("", encoding="utf-8")
            _append_flags_to_md(path, flags)
            return next((f for f in flags if f.id == flag_id), None)
    return None


def move_pending_to_handled(
    severity: FlagSeverity,
    observer_dir: Path | None = None,
) -> Path | None:
    """Move a pending flag file to cycles/handled/ and return the new path."""
    base = observer_dir or DEFAULT_OBSERVER_DIR
    src = _pending_path(severity, base)
    if not src.exists():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst_name = f"{severity.upper()}_FLAG_{ts}.md"
    dst = base / "cycles" / "handled" / dst_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)
    return dst
