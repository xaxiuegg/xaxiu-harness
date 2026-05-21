"""Dispatcher hooks for the canonical STATUS tracker.

These hooks are invoked from ``harness.engines.dispatcher.dispatch_packet``
and from the integrating supervisor.  Callers wrap each invocation in a
top-level ``try/except`` so STATUS tracking never breaks dispatch.

Convention: the STATUS.csv row id is the human-readable ``wave_id`` (e.g.
``W19-STATUS-TRACKER``) — that's the operator-facing identifier.  The
ephemeral per-dispatch ``task_id`` is recorded inside ``Notes`` so log
forensics can correlate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness.adapters.loader import _repo_root
from harness.status.schema import Status, StatusRow
from harness.status.store import (
    DEFAULT_STATUS_PATH,
    add_row,
    read_status,
    update_row,
)

__all__ = [
    "on_dispatch_start",
    "on_dispatch_complete",
    "on_commit",
    "default_csv_path",
]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def default_csv_path() -> Path:
    """Resolve the canonical STATUS.csv inside the active repo root."""
    try:
        return _repo_root() / DEFAULT_STATUS_PATH
    except Exception:
        return DEFAULT_STATUS_PATH


def _row_exists(path: Path, row_id: str) -> bool:
    try:
        rows = read_status(path)
    except (FileNotFoundError, ValueError):
        return False
    return any(r.id == row_id for r in rows)


def _truncate_notes(text: str) -> str:
    return text[:1000] if len(text) > 1000 else text


def on_dispatch_start(
    *,
    task_id: str,
    wave_id: str,
    engine: str,
    title: str | None = None,
    category: str = "Dispatch",
    owner: str | None = None,
    notes: str = "",
    path: Path | None = None,
) -> None:
    """Mark a wave as ``in_progress``.

    If a row with ``wave_id`` already exists, transitions it; otherwise
    appends a fresh row.  ``task_id`` is recorded inside the notes column
    for forensics.
    """
    p = path if path is not None else default_csv_path()
    note_parts = [f"task={task_id}", f"engine={engine}"]
    if notes:
        note_parts.append(notes)
    full_notes = _truncate_notes("; ".join(note_parts))
    resolved_owner = owner or "Claude"
    if _row_exists(p, wave_id):
        update_row(
            p,
            wave_id,
            status=Status.IN_PROGRESS.value,
            owner=resolved_owner,
            notes=full_notes,
        )
        return
    row = StatusRow(
        id=wave_id,
        category=category,
        title=(title or f"Dispatch {wave_id}"),
        status=Status.IN_PROGRESS,
        owner=resolved_owner,
        effort="-",
        updated=_today(),
        notes=full_notes,
    )
    add_row(p, row)


def on_dispatch_complete(
    *,
    task_id: str,
    wave_id: str,
    outcome: str,
    commit_sha: str | None = None,
    notes: str = "",
    path: Path | None = None,
) -> None:
    """Record a dispatch outcome.

    ``outcome`` is one of ``"success" | "shipped" | "partial" | "timeout" |
    "failure"``.  Maps to ``Status.SHIPPED`` (success/shipped),
    ``Status.PARTIAL`` (partial/timeout), or leaves the row in
    ``IN_PROGRESS`` (failure — dev manager decides next steps).

    Silently no-ops if ``wave_id`` is not present in the file (caller may
    have failed before ``on_dispatch_start`` ran).
    """
    p = path if path is not None else default_csv_path()
    if not _row_exists(p, wave_id):
        return
    outcome_to_status: dict[str, str] = {
        "success": Status.SHIPPED.value,
        "shipped": Status.SHIPPED.value,
        "partial": Status.PARTIAL.value,
        "timeout": Status.PARTIAL.value,
        "failure": Status.IN_PROGRESS.value,
    }
    new_status = outcome_to_status.get(outcome, Status.IN_PROGRESS.value)
    note_parts = [f"task={task_id}", f"outcome={outcome}"]
    if commit_sha:
        note_parts.append(f"commit={commit_sha[:12]}")
    if notes:
        note_parts.append(notes)
    full_notes = _truncate_notes("; ".join(note_parts))
    update_row(p, wave_id, status=new_status, notes=full_notes)


def on_commit(
    *,
    wave_id: str,
    commit_sha: str,
    files: list[str] | None = None,
    path: Path | None = None,
) -> None:
    """Record a commit landing; transitions the row to ``shipped``."""
    p = path if path is not None else default_csv_path()
    if not _row_exists(p, wave_id):
        return
    file_summary = f"; files={len(files)}" if files else ""
    update_row(
        p,
        wave_id,
        status=Status.SHIPPED.value,
        notes=_truncate_notes(f"commit={commit_sha[:12]}{file_summary}"),
    )
