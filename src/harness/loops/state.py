"""Loop state schema and atomic I/O for the dev-loop runner."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ActiveDispatch(BaseModel):
    """A dispatch currently in flight."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    packet: str
    engine: str
    dispatched_at: str
    phase: str
    wave_id: str | None = None
    timeout_seconds: int | None = None


class WaveEntry(BaseModel):
    """An entry in the wave plan."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    status: str
    depends_on: list[str] = Field(default_factory=list)
    completed_at: str | None = None


class LoopState(BaseModel):
    """Top-level mutable state for a single dev loop."""

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    loop_status: str = "armed"
    tick_count: int = 0
    last_tick_at: str | None = None
    phase_status: dict[str, str] = Field(default_factory=dict)
    active_dispatches: list[ActiveDispatch] = Field(default_factory=list)
    wave_plan: list[WaveEntry] = Field(default_factory=list)
    escalations: list[dict[str, Any]] = Field(default_factory=list)
    engine_slots: dict[str, Any] = Field(default_factory=dict)
    phase_cursors: dict[str, Any] = Field(default_factory=dict)
    event_log_path: str | None = None
    operator_directives: dict[str, Any] = Field(default_factory=dict)
    engine_cooldowns: dict[str, Any] = Field(default_factory=dict)
    dispatch_defaults: dict[str, Any] = Field(default_factory=dict)


def read_state(path: Path) -> LoopState:
    """Load a ``LoopState`` from *path*.

    Returns defaults on missing file, malformed JSON, or schema
    mismatch — callers wanting strict validation should call
    ``LoopState.model_validate`` directly.
    """
    if not path.exists():
        return LoopState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return LoopState.model_validate(raw)
    except (json.JSONDecodeError, ValidationError, ValueError):
        return LoopState()


def write_state(path: Path, state: LoopState) -> None:
    """Atomically write *state* to *path* using mkstemp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".loop_state_")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            json.dump(state.model_dump(mode="json"), fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
