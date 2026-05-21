"""Proxy state schemas and atomic persistence."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CircuitState(StrEnum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


class KeyState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    in_flight: int = Field(ge=0, default=0)
    max_concurrent: int = Field(ge=1, le=24, default=6)
    circuit_state: CircuitState = CircuitState.CLOSED
    recent_outcomes: list[str] = Field(default_factory=list, max_length=20)
    consecutive_failures: int = Field(ge=0, default=0)
    cooldown_until: str | None = None
    total_dispatched: int = Field(ge=0, default=0)
    total_failed: int = Field(ge=0, default=0)
    avg_latency_ms: float = Field(ge=0.0, default=0.0)
    last_used_at: str | None = None
    permanent: bool = False


class ProxyState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    started_at: str
    keys: dict[str, KeyState] = Field(default_factory=dict)
    routing_strategy: Literal["least_loaded", "round_robin", "random"] = "least_loaded"
    total_requests: int = Field(ge=0, default=0)
    total_errors: int = Field(ge=0, default=0)


def _default_state_path() -> Path:
    return Path(".harness") / "proxy_state.json"


def read_state(path: Path | None = None) -> ProxyState:
    if path is None:
        path = _default_state_path()
    if not path.exists():
        raise FileNotFoundError(f"State file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ProxyState.model_validate(data)


def write_state(state: ProxyState, path: Path | None = None) -> None:
    if path is None:
        path = _default_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(state.model_dump(mode="json"), f, indent=2)
            f.flush()
            os.fsync(tmp_fd)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
