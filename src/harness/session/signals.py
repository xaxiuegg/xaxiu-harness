"""Health signal collectors (psutil + filesystem + git)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

from pydantic import BaseModel

from harness.status import read_status

DEFAULT_STATE_PATH: Path = Path("coord/dev_loop/state.json")
DEFAULT_STATUS_PATH: Path = Path("coord/STATUS.csv")
DEFAULT_LOG_PATH: Path = Path("coord/dev_loop/log.jsonl")


class Signals(BaseModel):
    """Snapshot of session health signals."""

    session_age_hours: float
    tick_count: int
    active_dispatch_count: int
    commits_since_session: int
    status_csv_row_count: int
    mem_pct: float
    claude_rss_mb: int
    cpu_pct: float
    disk_pct_free: float
    jsonl_log_mb: float
    # NEW (2026-05-21 patch): the actual crash-risk file — Claude Code's
    # per-session transcript jsonl at ~/.claude/projects/<slug>/<uuid>.jsonl.
    # Grows monotonically per turn; calibrated thresholds 8/18/35 MB from
    # operator's historic session sizes (one prior session hit 52 MB ⇒ crash).
    claude_session_jsonl_mb: float = 0.0


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _session_age_hours(state: dict[str, Any]) -> float:
    started = state.get("created_at")
    if not started:
        return 0.0
    try:
        started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - started_dt).total_seconds() / 3600.0
    except Exception:
        return 0.0


def _git_commits_since(since_iso: str) -> int:
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"--since={since_iso}", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return 0


def _process_rss_mb() -> int:
    if psutil is None:
        return 0
    try:
        proc = psutil.Process()
        return int(proc.memory_info().rss / (1024 * 1024))
    except Exception:
        return 0


def _system_memory_pct() -> float:
    if psutil is None:
        return 0.0
    try:
        return psutil.virtual_memory().percent
    except Exception:
        return 0.0


def _cpu_pct() -> float:
    if psutil is None:
        return 0.0
    try:
        return psutil.cpu_percent(interval=0.5)
    except Exception:
        return 0.0


def _disk_pct_free() -> float:
    if psutil is None:
        return 100.0
    try:
        du = psutil.disk_usage("/")
        return du.free / du.total * 100
    except Exception:
        return 100.0


def _jsonl_log_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    try:
        return path.stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0


def _cwd_to_claude_slug(cwd: Path) -> str:
    """Encode cwd as Claude Code stores it: drive letter + '--' + parts.

    Examples (Windows):
      D:\\Projects             -> 'd--Projects'
      D:\\Projects\\xaxiu-harness -> 'd--Projects-xaxiu-harness'
    """
    drive = (cwd.drive or "").rstrip(":").lower()
    rel_parts = [p for p in cwd.parts[1:] if p not in ("\\", "/")]
    if not drive:
        return "-".join(rel_parts)
    return f"{drive}--" + "-".join(rel_parts) if rel_parts else f"{drive}--"


def _claude_session_jsonl_mb(cwd: Path | None = None) -> float:
    """Size of the active Claude Code session transcript in MB.

    Finds the most-recently-modified ``*.jsonl`` under
    ``~/.claude/projects/<slug>/`` where slug is derived from cwd.
    Returns 0.0 if not found (graceful when running outside Claude Code).
    """
    home = Path.home() / ".claude" / "projects"
    if not home.exists():
        return 0.0
    cwd = cwd or Path.cwd()
    # Try the obvious slug first; then fall back to scanning project dirs.
    candidates: list[Path] = []
    slug = _cwd_to_claude_slug(cwd)
    if slug:
        candidates.append(home / slug)
    # Walk up parents for slug match (e.g. cwd = .../xaxiu-harness/sub, slug = .../xaxiu-harness)
    for parent in cwd.parents:
        parent_slug = _cwd_to_claude_slug(parent)
        if parent_slug:
            candidates.append(home / parent_slug)
    seen: set[Path] = set()
    for proj_dir in candidates:
        if proj_dir in seen or not proj_dir.exists():
            seen.add(proj_dir)
            continue
        seen.add(proj_dir)
        try:
            jsonls = sorted(
                proj_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            continue
        if jsonls:
            try:
                return jsonls[0].stat().st_size / (1024 * 1024)
            except OSError:
                continue
    return 0.0


def collect_signals(
    state_path: Path = DEFAULT_STATE_PATH,
    status_path: Path = DEFAULT_STATUS_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
) -> Signals:
    """Gather all health signals and return a validated ``Signals`` model."""
    state = _load_state(state_path)
    session_age_hours = _session_age_hours(state)
    tick_count = state.get("tick_count", 0)
    active_dispatches = state.get("active_dispatches") or []
    active_dispatch_count = len(active_dispatches)
    started_at = state.get("created_at", "")
    commits_since_session = _git_commits_since(started_at) if started_at else 0
    status_rows = read_status(status_path)
    status_csv_row_count = len(status_rows)
    mem_pct = _system_memory_pct()
    claude_rss_mb = _process_rss_mb()
    cpu_pct = _cpu_pct()
    disk_pct_free = _disk_pct_free()
    jsonl_log_mb = _jsonl_log_mb(log_path)
    claude_session_jsonl_mb = _claude_session_jsonl_mb()
    return Signals(
        session_age_hours=round(session_age_hours, 2),
        tick_count=tick_count,
        active_dispatch_count=active_dispatch_count,
        commits_since_session=commits_since_session,
        status_csv_row_count=status_csv_row_count,
        mem_pct=round(mem_pct, 1),
        claude_rss_mb=claude_rss_mb,
        cpu_pct=round(cpu_pct, 1),
        disk_pct_free=round(disk_pct_free, 1),
        jsonl_log_mb=round(jsonl_log_mb, 2),
        claude_session_jsonl_mb=round(claude_session_jsonl_mb, 2),
    )
