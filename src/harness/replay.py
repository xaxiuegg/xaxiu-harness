"""Decision archaeology — reconstruct a dispatch's lifecycle.

Joins ``harness.state.db`` (dispatches + fallbacks) with
``harness.state.jsonl_log`` (engine_performance_log) to render a
chronological event timeline for a single dispatch_id.

Operator surface: ``harness replay <task_id>`` (CLI verb wired in
``harness.cli``).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.state import db as state_db

__all__ = [
    "ReplayEvent",
    "ReplayReport",
    "replay_dispatch",
    "format_for_human",
    "CoordRunReport",
    "replay_coord_run",
    "format_coord_for_human",
]


@dataclass
class ReplayEvent:
    """One step in a dispatch's lifecycle."""

    timestamp: str
    kind: str       # "dispatch_start" | "engine_call" | "fallback" | "dispatch_end"
    engine: str | None
    detail: str
    latency_ms: int | None = None


@dataclass
class ReplayReport:
    """Full timeline + summary for one dispatch."""

    task_id: str
    events: list[ReplayEvent] = field(default_factory=list)
    summary: str = ""
    total_elapsed_ms: int | None = None
    final_outcome: str | None = None


def _read_dispatch_row(task_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Return the dispatches row for ``task_id`` or None if missing.

    ``db_path`` is reserved for future v2 (per-call path override); the
    current connection is shared and configured via ``state_db.init_db``.
    """
    try:
        conn = state_db.get_connection()
    except Exception:
        return None
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, project, packet_path, backend, model, status, outcome,"
        " latency_ms, fallback_to, created_at FROM dispatches WHERE id = ?",
        (task_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, row))


def _read_fallback_rows(task_id: str) -> list[dict[str, Any]]:
    try:
        conn = state_db.get_connection()
    except Exception:
        return []
    cursor = conn.cursor()
    cursor.execute(
        "SELECT from_backend, to_backend, reason, timestamp"
        " FROM fallbacks WHERE dispatch_id = ? ORDER BY id ASC",
        (task_id,),
    )
    rows = cursor.fetchall()
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, r)) for r in rows]


def _read_jsonl_entries(
    project: str | None,
    packet_path: str | None,
    jsonl_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Best-effort fetch of jsonl entries matching project + packet_path."""
    if jsonl_path is None:
        from harness.state.jsonl_log import _log_path  # internal helper
        try:
            jsonl_path = _log_path()
        except Exception:
            return []
    p = Path(jsonl_path)
    if not p.exists():
        return []
    matches: list[dict[str, Any]] = []
    try:
        for raw_line in p.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if project is not None and entry.get("project") != project:
                continue
            if packet_path is not None and entry.get("packet_path") != packet_path:
                continue
            matches.append(entry)
    except OSError:
        return []
    return matches


def replay_dispatch(
    task_id: str,
    jsonl_path: Path | None = None,
    db_path: Path | None = None,  # noqa: ARG001 — reserved for future v2
) -> ReplayReport:
    """Reconstruct ``task_id``'s dispatch lifecycle.

    Returns a ``ReplayReport`` with ``events=[]`` and
    ``summary="(no events)"`` if the task_id is unknown — never raises
    on a stale or invalid id (operator may be querying old data).
    """
    report = ReplayReport(task_id=task_id, summary="(no events)")

    dispatch = _read_dispatch_row(task_id, db_path)
    if dispatch is None:
        # Maybe the task_id corresponds to a wave_id in jsonl rather than
        # a sqlite primary key.  Try a best-effort jsonl scan.
        jsonl_entries = _read_jsonl_entries(None, None, jsonl_path)
        matching = [e for e in jsonl_entries if task_id in str(e.values())]
        if not matching:
            return report
        for entry in matching:
            report.events.append(
                ReplayEvent(
                    timestamp=str(entry.get("timestamp", "")),
                    kind="engine_call",
                    engine=str(entry.get("backend", "")),
                    detail=f"jsonl: outcome={entry.get('outcome')}",
                    latency_ms=int(entry.get("latency_ms") or 0) or None,
                )
            )
        report.summary = f"{len(matching)} jsonl entries (no DB row)"
        return report

    # We have a sqlite row.
    report.events.append(
        ReplayEvent(
            timestamp=str(dispatch.get("created_at", "")),
            kind="dispatch_start",
            engine=str(dispatch.get("backend", "")),
            detail=(
                f"project={dispatch.get('project')} "
                f"packet={dispatch.get('packet_path')} "
                f"model={dispatch.get('model') or '-'}"
            ),
        )
    )

    for fb in _read_fallback_rows(task_id):
        report.events.append(
            ReplayEvent(
                timestamp=str(fb.get("timestamp", "")),
                kind="fallback",
                engine=str(fb.get("to_backend", "")),
                detail=f"from={fb.get('from_backend')} reason={fb.get('reason')}",
            )
        )

    # Final state — outcome from the dispatches row.
    final_engine = (
        str(dispatch.get("fallback_to") or dispatch.get("backend") or "")
        or None
    )
    report.events.append(
        ReplayEvent(
            timestamp=str(dispatch.get("created_at", "")),
            kind="dispatch_end",
            engine=final_engine,
            detail=f"status={dispatch.get('status')} outcome={dispatch.get('outcome') or '-'}",
            latency_ms=(
                int(dispatch.get("latency_ms"))
                if dispatch.get("latency_ms") is not None
                else None
            ),
        )
    )

    # Supplement with jsonl entries matching project + packet_path.
    jsonl_entries = _read_jsonl_entries(
        str(dispatch.get("project")),
        str(dispatch.get("packet_path")),
        jsonl_path,
    )
    for entry in jsonl_entries:
        outcome = str(entry.get("outcome", ""))
        report.events.append(
            ReplayEvent(
                timestamp=str(entry.get("timestamp", "")),
                kind="engine_call",
                engine=str(entry.get("backend", "")),
                detail=f"jsonl: outcome={outcome} fallback_to={entry.get('fallback_to') or '-'}",
                latency_ms=int(entry.get("latency_ms") or 0) or None,
            )
        )

    # Build summary.
    chain = [str(dispatch.get("backend", ""))]
    for fb in _read_fallback_rows(task_id):
        chain.append(str(fb.get("to_backend", "")))
    chain = [c for c in chain if c]
    arrows = " -> ".join(chain)
    final = dispatch.get("outcome") or dispatch.get("status") or "unknown"
    report.summary = f"{arrows} -> {final}" if arrows else str(final)
    report.total_elapsed_ms = (
        int(dispatch.get("latency_ms"))
        if dispatch.get("latency_ms") is not None
        else None
    )
    report.final_outcome = str(final)

    # Sort events by timestamp (lexically sortable because ISO 8601).
    report.events.sort(key=lambda e: e.timestamp)

    return report


def format_for_human(report: ReplayReport) -> str:
    """Render an operator-readable timeline.

    Output style mirrors `harness state inspect --format pretty` — a
    title line, a one-line summary, then a chronological event list.
    """
    lines: list[str] = []
    lines.append(f"Replay: {report.task_id}")
    lines.append(f"Summary: {report.summary}")
    if report.total_elapsed_ms is not None:
        lines.append(f"Total elapsed: {report.total_elapsed_ms} ms")
    if report.final_outcome:
        lines.append(f"Final outcome: {report.final_outcome}")
    lines.append("")
    if not report.events:
        lines.append("(no events recorded)")
        return "\n".join(lines)
    lines.append("Events:")
    for evt in report.events:
        engine = evt.engine or "-"
        latency = f" [{evt.latency_ms}ms]" if evt.latency_ms else ""
        lines.append(f"  {evt.timestamp}  {evt.kind:14}  {engine:18}  {evt.detail}{latency}")
    return "\n".join(lines)


@dataclasses.dataclass
class CoordRunReport:
    """Reconstructed lifecycle for one v2 coord run."""
    run_id: str
    state: str
    spec_path: str
    workers: list[dict]
    progress: list[dict]
    notify: dict | None
    total_events: int


def replay_coord_run(run_id: str, *, runs_dir: Path | None = None) -> CoordRunReport:
    """Reconstruct one v2 coord run from its on-disk artifacts.

    Reads runs/<run_id>/{run_state.json, plan.json, checkpoints/*, notify.json}
    and folds them into a single report ordered by per-step timestamp.
    """
    base = Path(runs_dir) if runs_dir else Path("runs")
    run_dir = base / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"no such run {run_dir}")

    def _load_json(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    run_state = _load_json(run_dir / "run_state.json")
    plan = _load_json(run_dir / "plan.json")
    notify = _load_json(run_dir / "notify.json") or None

    workers: list[dict] = []
    progress: list[dict] = []
    ckpt_dir = run_dir / "checkpoints"
    if ckpt_dir.exists():
        for p in sorted(ckpt_dir.glob("*.json")):
            data = _load_json(p)
            if data:
                workers.append(data)
        for p in sorted(ckpt_dir.glob("*.progress.jsonl")):
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ev["_worker_id"] = p.stem.replace(".progress", "")
                    progress.append(ev)
            except OSError:
                continue
    progress.sort(key=lambda e: e.get("ts", ""))

    return CoordRunReport(
        run_id=run_id,
        state=str(run_state.get("state", "unknown")),
        spec_path=str(plan.get("spec_path", "")),
        workers=workers,
        progress=progress,
        notify=notify,
        total_events=len(progress),
    )


def format_coord_for_human(report: CoordRunReport) -> str:
    lines: list[str] = []
    lines.append(f"run {report.run_id} (state: {report.state})")
    lines.append(f"  spec: {report.spec_path}")
    lines.append(f"  workers: {len(report.workers)}")
    for w in report.workers:
        wid = w.get("worker_id", "?")
        state = w.get("state", "?")
        sha = w.get("commit_sha") or "—"
        lines.append(f"    {wid}: {state}  commit={sha}")
    lines.append(f"  progress events: {report.total_events}")
    if report.notify:
        lines.append(f"  notify: success={report.notify.get('success')} commit={report.notify.get('commit_sha')}")
    return "\n".join(lines)
