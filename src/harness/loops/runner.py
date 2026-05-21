"""Dev-loop tick runner implementing the manager.md Steps 0-8."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from harness.loops.state import LoopState, read_state, write_state
from harness.loops.supervisors import SupervisorResult, run_supervisor
from harness.observer.flags import FlagSeverity, list_pending_flags


# Canonical merge order for supervisor diffs
_MERGE_ORDER = [
    "creativity",
    "testing",
    "developing",
    "integrating",
    "process_improvement",
]


def _iso_to_dt(iso: str) -> datetime:
    """Parse an ISO-8601 string to a timezone-aware datetime."""
    # Handle Z suffix
    iso = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(iso)


def _dt_to_iso(dt: datetime) -> str:
    """Format a datetime as ISO-8601 UTC string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_nested(data: dict[str, Any], key: str) -> Any:
    """Read a dot-separated key from a nested dict."""
    parts = key.split(".")
    for part in parts:
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _set_nested(data: dict[str, Any], key: str, value: Any) -> None:
    """Write a dot-separated key into a nested dict, creating intermediates."""
    parts = key.split(".")
    for part in parts[:-1]:
        if part not in data or not isinstance(data[part], dict):
            data[part] = {}
        data = data[part]
    data[parts[-1]] = value


def _apply_diff(state: LoopState, diff: dict[str, Any]) -> None:
    """Apply a flat dict of dot-notation keys to *state* in place."""
    raw = state.model_dump(mode="json")
    for key, value in diff.items():
        _set_nested(raw, key, value)
    merged = LoopState.model_validate(raw)
    # Mutate in place by replacing __dict__ contents (Pydantic v2 compat)
    for name, val in merged:
        object.__setattr__(state, name, val)


def _atomic_append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON line to *path* atomically via temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        content = existing.rstrip("\n") + "\n" + line + "\n"
    else:
        content = line + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".loop_log_")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _escalation_backoff(attempt: int) -> int:
    """Exponential backoff capped at 14400 seconds (4 hours)."""
    return min(60 * (2 ** attempt), 14400)


@dataclass
class TickResult:
    """Structured return value from a single tick."""

    tick_count: int
    phases_acted_on: list[str] = field(default_factory=list)
    state_diff_summary: str = ""
    escalations_raised: list[dict[str, Any]] = field(default_factory=list)
    observer_flags_seen: list[str] = field(default_factory=list)
    next_due_at: str | None = None
    kill_triggered: str | None = None  # which kill_condition fired, if any


def _check_kill_conditions(state: LoopState, project: Path) -> str | None:
    """Return the name of the kill condition that fired, or None.

    Reads ``operator.kill_conditions`` from the active adapter YAML (if any)
    and compares against the loop's accumulated stats.  Conditions that are
    None (the default) are disabled.

    Returns the dotted condition name (e.g. ``"max_cost_usd"``) that fired
    so the caller can record an L4 escalation and stop the loop.
    """
    try:
        from harness.adapters.loader import load_project_adapter
        from harness.budget import total_spent
    except Exception:
        return None

    project_name = getattr(state, "project_name", None)
    if not project_name:
        return None

    try:
        adapter = load_project_adapter(project_name)
    except Exception:
        return None

    op = getattr(adapter, "operator", None)
    if op is None:
        return None
    kc = getattr(op, "kill_conditions", None)
    if kc is None:
        return None

    # max_cost_usd
    cost_cap = getattr(kc, "max_cost_usd", None)
    if cost_cap is not None:
        try:
            spent = total_spent()
        except Exception:
            spent = 0.0
        if spent >= cost_cap:
            return "max_cost_usd"

    # max_rows_dispatched
    rows_cap = getattr(kc, "max_rows_dispatched", None)
    if rows_cap is not None and state.tick_count >= rows_cap:
        return "max_rows_dispatched"

    # max_wallclock_minutes
    wall_cap = getattr(kc, "max_wallclock_minutes", None)
    if wall_cap is not None and state.started_at:
        try:
            started = _iso_to_dt(state.started_at)
            elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60.0
            if elapsed_min >= wall_cap:
                return "max_wallclock_minutes"
        except Exception:
            pass

    return None


def tick(
    state_path: Path,
    observer_dir: Path | None,
    project: Path,
    now: datetime | None = None,
) -> TickResult:
    """Execute one dev-loop tick.

    Parameters
    ----------
    state_path:
        Path to the ``state.json`` file.
    observer_dir:
        Path to the observer directory (may be ``None``).
    project:
        Path to the project root.
    now:
        Override the current time (defaults to UTC now).
    """
    now = now or datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Step 0: observer flags
    # ------------------------------------------------------------------
    observer_flags_seen: list[str] = []
    if observer_dir is not None and observer_dir.exists():
        pending = list_pending_flags(observer_dir)
        for sev in (FlagSeverity.HIGH, FlagSeverity.CRITICAL):
            for flag in pending.get(sev, []):
                observer_flags_seen.append(f"{sev.value}:{flag.id}")

    # ------------------------------------------------------------------
    # Steps 1-2: load state, gate on loop_status
    # ------------------------------------------------------------------
    state = read_state(state_path)

    if state.loop_status != "armed":
        log_entry = {
            "tick": state.tick_count,
            "at": _dt_to_iso(now),
            "event": "tick_refused",
            "reason": f"loop_status={state.loop_status}",
            "phases_acted_on": [],
        }
        if state.event_log_path:
            _atomic_append_jsonl(project / state.event_log_path, log_entry)
        return TickResult(
            tick_count=state.tick_count,
            phases_acted_on=[],
            observer_flags_seen=observer_flags_seen,
        )

    # ------------------------------------------------------------------
    # Step 2.5: kill-conditions gate (KILL-CONDITION-WIRING)
    # ------------------------------------------------------------------
    killer = _check_kill_conditions(state, project)
    if killer is not None:
        # Stop the loop, record an L4 escalation, and refuse this tick.
        state.loop_status = "stopped"
        state.escalations.append({
            "severity": "L4",
            "code": f"E_KILL_{killer.upper()}",
            "at": _dt_to_iso(now),
            "reason": f"kill_condition {killer} exceeded; loop stopped",
        })
        write_state(state_path, state)
        log_entry = {
            "tick": state.tick_count,
            "at": _dt_to_iso(now),
            "event": "tick_killed",
            "kill_condition": killer,
            "phases_acted_on": [],
        }
        if state.event_log_path:
            _atomic_append_jsonl(project / state.event_log_path, log_entry)
        return TickResult(
            tick_count=state.tick_count,
            phases_acted_on=[],
            observer_flags_seen=observer_flags_seen,
            kill_triggered=killer,
            escalations_raised=[state.escalations[-1]],
        )

    # ------------------------------------------------------------------
    # Step 3: check active dispatches for completion
    # ------------------------------------------------------------------
    # Wave 6/A: no external dispatch tracker wired yet; leave untouched.

    # ------------------------------------------------------------------
    # Step 4: pick eligible phases
    # ------------------------------------------------------------------
    eligible: list[str] = []
    for phase in _MERGE_ORDER:
        status = state.phase_status.get(phase)
        if status != "armed":
            continue
        cursor = state.phase_cursors.get(phase, {}) if isinstance(state.phase_cursors, dict) else {}
        if not isinstance(cursor, dict):
            cursor = {}
        next_due = cursor.get("next_due_at")
        if next_due is None:
            # No schedule yet — treat as eligible (first-run semantics)
            eligible.append(phase)
        else:
            try:
                due_dt = _iso_to_dt(next_due)
                if due_dt <= now:
                    eligible.append(phase)
            except Exception:
                # Malformed timestamp — treat as eligible to unstick
                eligible.append(phase)

    # ------------------------------------------------------------------
    # Step 5: run supervisors with conflict detection
    # ------------------------------------------------------------------
    results: dict[str, SupervisorResult] = {}
    selected_write_sets: list[set[str]] = []

    for phase in eligible:
        result = run_supervisor(phase, state, project=project, now=now)
        # Conflict detection
        if result.write_set and any(
            bool(set(result.write_set) & ws) for ws in selected_write_sets
        ):
            continue
        results[phase] = result
        if result.write_set:
            selected_write_sets.append(set(result.write_set))

    # ------------------------------------------------------------------
    # Step 6: merge state diffs in canonical order
    # ------------------------------------------------------------------
    phases_acted_on: list[str] = []
    escalations_raised: list[dict[str, Any]] = []

    for phase in _MERGE_ORDER:
        if phase not in results:
            continue
        result = results[phase]
        phases_acted_on.append(phase)
        if result.state_diff:
            _apply_diff(state, result.state_diff)
        if result.escalation:
            escalation = dict(result.escalation)
            escalation["phase"] = phase
            escalation["raised_at"] = _dt_to_iso(now)
            state.escalations.append(escalation)
            escalations_raised.append(escalation)
            # Mark phase paused with exponential backoff
            state.phase_status[phase] = "paused_by_escalation"
            attempt = sum(
                1
                for e in state.escalations
                if e.get("phase") == phase and e.get("level") == escalation.get("level")
            )
            backoff_seconds = _escalation_backoff(attempt - 1)
            next_retry = now + timedelta(seconds=backoff_seconds)
            if isinstance(state.phase_cursors, dict):
                pc = state.phase_cursors.setdefault(phase, {})
                if isinstance(pc, dict):
                    pc["next_due_at"] = _dt_to_iso(next_retry)

    # ------------------------------------------------------------------
    # Step 7: append structured log entry
    # ------------------------------------------------------------------
    state.tick_count += 1
    state.last_tick_at = _dt_to_iso(now)
    log_entry = {
        "tick": state.tick_count,
        "at": state.last_tick_at,
        "phases_acted_on": phases_acted_on,
        "escalations_raised": [e.get("tag", "unknown") for e in escalations_raised],
        "observer_flags_seen": observer_flags_seen,
    }
    if state.event_log_path:
        _atomic_append_jsonl(project / state.event_log_path, log_entry)

    # ------------------------------------------------------------------
    # Step 8: atomic write state
    # ------------------------------------------------------------------
    write_state(state_path, state)

    # Compute next global due time (earliest next_due_at across phases)
    next_due_candidates: list[str] = []
    for phase in _MERGE_ORDER:
        if isinstance(state.phase_cursors, dict):
            pc = state.phase_cursors.get(phase, {})
            if isinstance(pc, dict):
                nd = pc.get("next_due_at")
                if nd and state.phase_status.get(phase) == "armed":
                    next_due_candidates.append(nd)

    next_due_at = min(next_due_candidates) if next_due_candidates else None

    return TickResult(
        tick_count=state.tick_count,
        phases_acted_on=phases_acted_on,
        state_diff_summary=f"phases={phases_acted_on}",
        escalations_raised=escalations_raised,
        observer_flags_seen=observer_flags_seen,
        next_due_at=next_due_at,
    )
