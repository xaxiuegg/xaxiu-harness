"""Operator-friendly pretty-printer for ``coord/dev_loop/state.json``.

Surfaces dev-loop runtime state to non-technical operators without
requiring Python or JSON-literacy.  See roster row #18 (companion to
heartbeat row #17).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.errors import ConfigCorruption

__all__ = [
    "DEFAULT_STATE_PATH",
    "render_state_json",
    "summarize_wave_plan",
    "summarize_active_dispatches",
    "summarize_phase_statuses",
    "summarize_engine_slots",
]


DEFAULT_STATE_PATH: Path = Path("coord/dev_loop/state.json")


def _load_state(path: Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"state file not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigCorruption(
            f"state.json is not valid JSON: {exc}",
            context={"path": str(p)},
        ) from exc


def summarize_wave_plan(wave_plan: list[dict[str, Any]] | None) -> str:
    if not wave_plan:
        return "(none)"
    counts: dict[str, int] = {}
    by_status: dict[str, list[str]] = {}
    for w in wave_plan:
        st = str(w.get("status", "?"))
        counts[st] = counts.get(st, 0) + 1
        by_status.setdefault(st, []).append(str(w.get("id", "?")))
    summary = " / ".join(f"{n} {st}" for st, n in sorted(counts.items()))
    return summary


def summarize_active_dispatches(dispatches: list[dict[str, Any]] | None) -> str:
    if not dispatches:
        return "(none)"
    lines = []
    for d in dispatches:
        task_id = d.get("task_id", "?")
        engine = d.get("engine", "?")
        wave = d.get("wave_id", "-")
        started = d.get("dispatched_at", "-")
        lines.append(f"  {task_id}  {engine}  {wave}  started {started}")
    return "\n".join(lines)


def summarize_phase_statuses(phase_status: dict[str, str] | None) -> str:
    if not phase_status:
        return "(none)"
    armed = [name for name, s in phase_status.items() if s == "armed"]
    other = [(name, s) for name, s in phase_status.items() if s != "armed"]
    if not other:
        return f"all {len(armed)} armed ({', '.join(sorted(armed))})"
    parts = [f"{len(armed)} armed"]
    parts.extend(f"{name} {s}" for name, s in other)
    return ", ".join(parts)


def summarize_engine_slots(engine_slots: dict[str, Any] | None) -> str:
    if not engine_slots:
        return "(none)"
    parts: list[str] = []
    for name in ("kimi", "kimi-api", "deepseek"):
        block = engine_slots.get(name) or {}
        if not isinstance(block, dict):
            continue
        in_flight = block.get("in_flight") or []
        max_p = block.get("max_parallel", "-")
        n = len(in_flight) if isinstance(in_flight, list) else 0
        parts.append(f"{name} {n}/{max_p}")
    return ", ".join(parts) if parts else "(none)"


def render_state_json(
    path: Path = DEFAULT_STATE_PATH,
    fmt: str = "pretty",
) -> str:
    """Render state.json for the operator.

    ``fmt`` is one of ``"pretty"`` (multi-section human summary),
    ``"json"`` (raw pass-through for piping), or ``"compact"``
    (single-line key=value).
    """
    state = _load_state(Path(path))
    if fmt == "json":
        return json.dumps(state, indent=2, sort_keys=True)
    if fmt == "compact":
        wave_plan = state.get("wave_plan") or []
        active = state.get("active_dispatches") or []
        return (
            f"loop={state.get('loop_status', '?')} "
            f"tick={state.get('tick_count', '?')} "
            f"last={state.get('last_tick_at', '?')} "
            f"active={len(active)} "
            f"wave_plan={summarize_wave_plan(wave_plan)}"
        )
    lines: list[str] = []
    lines.append(
        f"Loop: {state.get('loop_status', '?')} | "
        f"tick #{state.get('tick_count', '?')} | "
        f"last pulsed {state.get('last_tick_at', '?')}"
    )
    lines.append("")
    lines.append(f"Phases: {summarize_phase_statuses(state.get('phase_status'))}")
    lines.append("")
    active = state.get("active_dispatches") or []
    lines.append(f"Active dispatches ({len(active)}):")
    lines.append(summarize_active_dispatches(active))
    lines.append("")
    wave_plan = state.get("wave_plan") or []
    lines.append(f"Wave plan: {summarize_wave_plan(wave_plan)}")
    if wave_plan:
        by_status: dict[str, list[str]] = {}
        for w in wave_plan:
            by_status.setdefault(str(w.get("status", "?")), []).append(str(w.get("id", "?")))
        for st in ("in_progress", "done", "planned", "blocked"):
            if st in by_status:
                lines.append(f"  {st}: {', '.join(by_status[st])}")
    lines.append("")
    escs = state.get("escalations") or []
    if escs:
        lines.append(f"Escalations: {len(escs)} active")
        for e in escs[-3:]:
            lines.append(f"  {e.get('id', '?')} {e.get('tag', '?')}: {e.get('diagnostic', '')[:80]}")
    else:
        lines.append("Escalations: none active")
    lines.append(f"Engine slots: {summarize_engine_slots(state.get('engine_slots'))}")
    return "\n".join(lines)
