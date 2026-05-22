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
    status_csv: Path | None = None,
) -> bool:
    """Return True if creativity supervisor appears to have run within *window_seconds*.

    Robust signal — checks BOTH:
    1. dev_loop/log.jsonl recently modified (productized loop creativity), OR
    2. STATUS.csv was modified within the window (interactive Agent-tool
       creativity invocations write new rows to STATUS.csv directly).

    Either path counts.  We need only one positive signal so the gate
    doesn't issue false negatives during interactive sessions where
    creativity is fired via Agent rather than the dev-loop runner.

    *status_csv* is parameterized for testability — leave at default
    (None → live STATUS.csv) in production.
    """
    # Path 1: dev_loop log mtime
    try:
        if log_path.exists():
            age = time.time() - log_path.stat().st_mtime
            if age <= window_seconds:
                return True
    except OSError:
        pass

    # Path 2: STATUS.csv was modified within the window
    status_csv = status_csv if status_csv is not None else _STATUS_CSV
    try:
        if status_csv.exists():
            age = time.time() - status_csv.stat().st_mtime
            if age <= window_seconds:
                return True
    except OSError:
        pass

    return False


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
    """Return (ok, reason) — back-compat 2-tuple shape."""
    ok, reason, _ = ok_to_stop_with_inputs()
    return ok, reason


def ok_to_stop_with_inputs() -> tuple[bool, str, dict]:
    """Return (ok, reason, inputs) where inputs is the structured decision basis.

    inputs schema:
      session_handoff_recommendation: str  (NONE|SOFT|STRONGLY|CRITICAL)
      production_queued: int
      creativity_fired_within_minutes: int | None  (None = never within window)
      approval_file_present: bool

    WIRE-OK-TO-STOP-JSON (2026-05-22): added for the --json CLI surface.
    """
    rec = _session_handoff_recommendation()
    approval = _OPERATOR_STOP_FLAG.exists()
    queued = _count_queued_production_rows()
    # creativity_fired_within_minutes: derive from log mtime
    creativity_minutes: int | None = None
    if _CREATIVITY_LOG.exists():
        age_s = time.time() - _CREATIVITY_LOG.stat().st_mtime
        if age_s <= _CREATIVITY_WINDOW_SECONDS:
            creativity_minutes = int(age_s // 60)
    inputs = {
        "session_handoff_recommendation": rec,
        "production_queued": queued,
        "creativity_fired_within_minutes": creativity_minutes,
        "approval_file_present": approval,
    }

    # 1. Session-handoff threshold
    if rec in ("STRONGLY", "CRITICAL"):
        return True, f"session-handoff recommendation is {rec} — stop is appropriate", inputs

    # 2. Operator explicit stop flag
    if approval:
        return True, f"operator stop flag present: {_OPERATOR_STOP_FLAG}", inputs

    # 3. Backlog + creativity attempt
    if queued == 0:
        if creativity_minutes is not None:
            return True, (
                "0 queued production rows AND creativity supervisor "
                "fired recently — backlog genuinely drained"
            ), inputs
        return False, (
            "0 queued production rows but creativity has not fired in "
            f"the last {_CREATIVITY_WINDOW_SECONDS // 60}min — "
            "fire `creativity supervisor` to repopulate backlog before stopping"
        ), inputs

    return False, (
        f"{queued} queued production rows still pending; "
        f"session-handoff rec is {rec} (well below STRONGLY).  "
        "Continue dispatching work."
    ), inputs
