"""Passive dev-manager liveness signal for the operator.

The dev manager pulses to ``coord/dev_loop/heartbeat.json`` each tick;
``harness heartbeat show`` reads the file and renders a one-second
operator-friendly summary.  Answer to roster row #17 — "is the loop
alive?" without scrolling chat history.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Heartbeat",
    "HEARTBEAT_PATH",
    "STATE_PATH",
    "pulse",
    "read_heartbeat",
    "format_for_human",
]


HEARTBEAT_PATH: Path = Path("coord/dev_loop/heartbeat.json")
STATE_PATH: Path = Path("coord/dev_loop/state.json")

_ISO_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$"


class Heartbeat(BaseModel):
    """Snapshot of dev-loop liveness, derived from state.json."""

    model_config = ConfigDict(extra="forbid")

    pulsed_at: str = Field(pattern=_ISO_RE)
    tick_count: int = Field(ge=0)
    loop_status: str
    active_dispatches: int = Field(ge=0)
    in_flight_kimi: int = Field(ge=0)
    in_flight_deepseek: int = Field(ge=0)
    phase_statuses: dict[str, str] = Field(default_factory=dict)
    last_escalation_id: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _engine_inflight(state: dict[str, Any], engine: str) -> int:
    slots = state.get("engine_slots") or {}
    block = slots.get(engine)
    if not isinstance(block, dict):
        block = {}
    in_flight = block.get("in_flight") or []
    return len(in_flight) if isinstance(in_flight, list) else 0


def _last_escalation_id(state: dict[str, Any]) -> str | None:
    escs = state.get("escalations") or []
    if not isinstance(escs, list) or not escs:
        return None
    last = escs[-1]
    if isinstance(last, dict):
        return last.get("id")
    return None


def pulse(
    state_path: Path = STATE_PATH,
    heartbeat_path: Path = HEARTBEAT_PATH,
) -> Heartbeat:
    """Read ``state_path``, derive a ``Heartbeat``, write atomically.

    Raises ``FileNotFoundError`` if ``state_path`` is missing — the dev
    manager calls this from inside an established loop, so a missing
    state file is a real error rather than a no-op.
    """
    p = Path(state_path)
    if not p.exists():
        raise FileNotFoundError(f"state file missing: {p}")
    state = json.loads(p.read_text(encoding="utf-8"))
    active = state.get("active_dispatches") or []
    beat = Heartbeat(
        pulsed_at=_now_iso(),
        tick_count=_safe_int(state.get("tick_count", 0)),
        loop_status=str(state.get("loop_status", "unknown")),
        active_dispatches=len(active) if isinstance(active, list) else 0,
        in_flight_kimi=_engine_inflight(state, "kimi"),
        in_flight_deepseek=_engine_inflight(state, "deepseek"),
        phase_statuses=dict(state.get("phase_status") or {}),
        last_escalation_id=_last_escalation_id(state),
    )
    _atomic_write(Path(heartbeat_path), beat.model_dump(mode="json"))
    return beat


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".heartbeat_", suffix=".json")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def read_heartbeat(path: Path = HEARTBEAT_PATH) -> Heartbeat | None:
    """Load the latest heartbeat; return ``None`` if missing."""
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return Heartbeat.model_validate(data)


def _age_seconds(beat: Heartbeat, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    try:
        pulsed = datetime.strptime(beat.pulsed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        pulsed = datetime.fromisoformat(beat.pulsed_at.replace("Z", "+00:00"))
    return (now - pulsed).total_seconds()


def format_for_human(
    beat: Heartbeat | None,
    now: datetime | None = None,
    stale_after_seconds: float = 300.0,
) -> str:
    """Render a 3-5 line operator-readable summary."""
    if beat is None:
        return "Heartbeat: never (no pulse recorded)"
    age = _age_seconds(beat, now)
    age_str = (
        f"{int(age)}s ago"
        if age < 60
        else f"{int(age // 60)}m {int(age % 60)}s ago"
    )
    stale_prefix = "STALE - " if age > stale_after_seconds else ""
    lines = [
        f"{stale_prefix}Heartbeat: {age_str} (tick #{beat.tick_count}, status {beat.loop_status})",
        f"Dispatches: {beat.active_dispatches} active "
        f"({beat.in_flight_kimi} kimi, {beat.in_flight_deepseek} deepseek)",
    ]
    if beat.phase_statuses:
        phases = ", ".join(
            f"{name} {status}" for name, status in sorted(beat.phase_statuses.items())
        )
        lines.append(f"Phases: {phases}")
    if beat.last_escalation_id:
        lines.append(f"Last escalation: {beat.last_escalation_id}")
    else:
        lines.append("No active escalations.")
    return "\n".join(lines)
