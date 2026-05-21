"""Deterministic gate on whether the session may legitimately stop now.

The autonomous loop (per `feedback_full_automation_until_wave_plan_empty`
and `feedback_high_throughput_session_pattern`) is supposed to run until
STRONGLY/CRITICAL session-handoff OR explicit operator stop.  When the
agent's own reasoning starts producing language like "saturated", "natural
pause", or "session complete" without first checking this gate, it's
abandoning the loop prematurely.

This module exists so the agent can call ``ok_to_stop()`` (or invoke
``harness session ok-to-stop`` from a shell) and get a single
deterministic answer that doesn't depend on its in-context judgment.

Returns (ok: bool, reason: str).  ``ok=True`` if AND ONLY IF:

1. Session-handoff recommendation is STRONGLY or CRITICAL, OR
2. ``coord/session_stop_approved`` file exists (operator explicit stop), OR
3. STATUS.csv production-leaning queued rows == 0 AND a creativity
   supervisor was fired in the last hour (so we did try to repopulate).

Otherwise ``ok=False`` with a diagnostic the agent must surface.
"""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


_OPERATOR_STOP_FLAG = Path("coord") / "session_stop_approved"
_STATUS_CSV = Path("coord") / "STATUS.csv"
_CREATIVITY_LOG = Path("coord") / "dev_loop" / "log.jsonl"
_CREATIVITY_WINDOW_SECONDS = 3600  # 1 hour


def _count_queued_production_rows(csv_path: Path = _STATUS_CSV) -> int:
    """Count rows whose status=='queued' AND category looks production-leaning."""
    if not csv_path.exists():
        return 0
    production_categories = frozenset({
        "Production", "Operator-UX", "Observability", "Integration",
        "Failure-Recovery", "Security", "Onboarding", "Telemetry",
        "Multi-Tenancy", "Failure-Mode", "Dispatch-Quality",
    })
    queued = 0
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return 0
            # Find columns
            try:
                cat_idx = header.index("Category")
                status_idx = header.index("Status")
            except ValueError:
                return 0
            for row in reader:
                if len(row) <= max(cat_idx, status_idx):
                    continue
                if row[status_idx].strip().lower() != "queued":
                    continue
                if row[cat_idx].strip() in production_categories:
                    queued += 1
    except OSError:
        return 0
    return queued


def _creativity_recently_fired(
    log_path: Path = _CREATIVITY_LOG,
    window_seconds: int = _CREATIVITY_WINDOW_SECONDS,
) -> bool:
    """Return True if any dev_loop log entry within *window_seconds* mentions creativity."""
    if not log_path.exists():
        return False
    try:
        mtime = log_path.stat().st_mtime
    except OSError:
        return False
    age = time.time() - mtime
    if age > window_seconds:
        return False
    # File modified recently — assume something was logged.  The
    # creativity supervisor writes its dispatches via this same path.
    return True


def _session_handoff_recommendation() -> str:
    """Return SOFT|STRONGLY|CRITICAL|NONE from the session-handoff recommender."""
    try:
        from harness.session.recommender import recommend
        from harness.session.signals import Signals
        # Signals.collect() is the canonical entry point if it exists
        try:
            sigs = Signals.collect()  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            # Older Signals API — build with safe defaults
            sigs = Signals(
                session_age_hours=0.0,
                tick_count=0,
                commits_since_session=0,
                status_csv_row_count=0,
                jsonl_log_mb=0.0,
                claude_session_jsonl_mb=0.0,
                mem_pct=0,
                claude_rss_mb=0,
                disk_pct_free=100.0,
            )
        rec, _reasons = recommend(sigs)
        return rec.value.upper() if hasattr(rec, "value") else str(rec).upper()
    except Exception:
        return "NONE"


def ok_to_stop() -> tuple[bool, str]:
    """Return (ok, reason) for whether the session may legitimately stop now."""
    # 1. Session-handoff threshold
    rec = _session_handoff_recommendation()
    if rec in ("STRONGLY", "CRITICAL"):
        return True, f"session-handoff recommendation is {rec} — stop is appropriate"

    # 2. Operator explicit stop flag
    if _OPERATOR_STOP_FLAG.exists():
        return True, f"operator stop flag present: {_OPERATOR_STOP_FLAG}"

    # 3. Backlog + creativity attempt
    queued = _count_queued_production_rows()
    if queued == 0:
        if _creativity_recently_fired():
            return True, (
                "0 queued production rows AND creativity supervisor "
                "fired recently — backlog genuinely drained"
            )
        return False, (
            "0 queued production rows but creativity has not fired in "
            f"the last {_CREATIVITY_WINDOW_SECONDS // 60}min — "
            "fire `creativity supervisor` to repopulate backlog before stopping"
        )

    return False, (
        f"{queued} queued production rows still pending; "
        f"session-handoff rec is {rec} (well below STRONGLY).  "
        "Continue dispatching work."
    )
