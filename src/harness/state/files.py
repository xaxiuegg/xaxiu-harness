"""Pydantic-typed read/write helpers for JSON+YAML state files.

Covers v1 §4 state files:
  - harness.config.yml
  - state/active_dispatches.json
  - state/loops.json
  - state/engine_health.json

Security rules from v1.2 amendments:
  - yaml.safe_load ONLY (HIGH-7)
  - Atomic writes + fsync + 0600 mode (sensitive runtime state)
  - Corrupted files raise StateFileCorruptError with path only, NEVER content (LOW-3)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, field_validator

from harness._constants import STATE_DIR as _SHARED_STATE_DIR

from harness._constants import TASK_NAME_PREFIX

# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class StateFileCorruptError(Exception):
    """Raised when a state file exists but cannot be parsed.

    The exception message MUST contain only the file path, never the raw
    file contents (v1.2 LOW-3).
    """

    def __init__(self, path: Path) -> None:
        super().__init__(f"State file is corrupt: {path}")
        self.path = path


# ---------------------------------------------------------------------------
# State directory resolution
# ---------------------------------------------------------------------------

#: Sourced from harness._constants to keep a single source of truth across
#: files.py, dpapi.py, and db.py (Wave 2A MED fix: previously each module
#: resolved its own state dir, causing split-brain when cwd diverged).
STATE_DIR: Path = _SHARED_STATE_DIR


def _ensure_state_dir() -> None:
    """Create the state directory if it does not yet exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class HarnessConfig(BaseModel):
    harness_version: str
    default_project: str | None = None
    installed: bool = False
    task_scheduler_prefix: str = TASK_NAME_PREFIX
    model_config = {"extra": "forbid"}


class ActiveDispatch(BaseModel):
    dispatch_id: str              # UUID
    project: str
    packet_path: str
    backend: Literal["deepseek", "kimi", "anthropic", "gemini", "mock"]
    model: str | None = None
    started_at: str               # ISO 8601 UTC
    status: Literal["running", "complete", "failed", "fallback"]
    fallback_count: int = 0
    current_backend: str | None = None
    model_config = {"extra": "forbid"}


class LoopEntry(BaseModel):
    name: str
    command: str                  # must start with "harness "
    cron: str
    enabled: bool = True
    task_name: str                # full Windows Task Scheduler name
    model_config = {"extra": "forbid"}

    @field_validator("command")
    @classmethod
    def _command_must_start_with_harness(cls, v: str) -> str:
        if not v.startswith("harness "):
            raise ValueError("command must start with 'harness '")
        return v


class EngineHealth(BaseModel):
    status: Literal["up", "degraded", "down"] = "up"
    last_fail: str | None = None  # ISO 8601 UTC
    avg_latency_ms: int | None = None
    priority: Literal["HIGH", "NORMAL", "AVOID"] = "NORMAL"
    burst_until: str | None = None
    locked: bool = False
    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _set_mode_0600(path: Path) -> None:
    """Restrict file permissions to owner-read/write (0600).

    Wave 2A HIGH fix: removed the broken pywin32 DACL branch (claimed to
    deny-everyone but only added an allow-ACE, AND pywin32 was undeclared in
    pyproject.toml — build-breaker on clean install). On Windows ``os.chmod``
    sets read-only; full ACL hardening is deferred to a v1.x installer task.
    """
    os.chmod(path, 0o600)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Serialize *data* to JSON and atomically replace *path*."""
    _ensure_state_dir()
    fd, tmp_name = tempfile.mkstemp(dir=STATE_DIR, suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fd)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, path)
    _set_mode_0600(path)


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Serialize *data* to YAML and atomically replace *path*."""
    _ensure_state_dir()
    fd, tmp_name = tempfile.mkstemp(dir=STATE_DIR, suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
            fh.flush()
            os.fsync(fd)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, path)
    _set_mode_0600(path)


# ---------------------------------------------------------------------------
# harness.config.yml
# ---------------------------------------------------------------------------

HARNESS_CONFIG_PATH: Path = STATE_DIR / "harness.config.yml"


def read_harness_config() -> HarnessConfig:
    """Read harness.config.yml; return defaults when missing."""
    if not HARNESS_CONFIG_PATH.exists():
        return HarnessConfig(harness_version="1.2.0")
    try:
        with HARNESS_CONFIG_PATH.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise StateFileCorruptError(HARNESS_CONFIG_PATH) from exc
    if raw is None:
        raw = {}
    try:
        return HarnessConfig.model_validate(raw)
    except Exception as exc:
        raise StateFileCorruptError(HARNESS_CONFIG_PATH) from exc


def write_harness_config(cfg: HarnessConfig) -> None:
    """Persist *cfg* to harness.config.yml atomically."""
    _atomic_write_yaml(HARNESS_CONFIG_PATH, cfg.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# active_dispatches.json
# ---------------------------------------------------------------------------

ACTIVE_DISPATCHES_PATH: Path = STATE_DIR / "active_dispatches.json"


def read_active_dispatches() -> list[ActiveDispatch]:
    """Read active_dispatches.json; return empty list when missing."""
    if not ACTIVE_DISPATCHES_PATH.exists():
        return []
    try:
        with ACTIVE_DISPATCHES_PATH.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise StateFileCorruptError(ACTIVE_DISPATCHES_PATH) from exc
    if not isinstance(raw, list):
        raise StateFileCorruptError(ACTIVE_DISPATCHES_PATH)
    try:
        return [ActiveDispatch.model_validate(item) for item in raw]
    except Exception as exc:
        raise StateFileCorruptError(ACTIVE_DISPATCHES_PATH) from exc


def write_active_dispatches(items: list[ActiveDispatch]) -> None:
    """Overwrite active_dispatches.json atomically."""
    payload = [item.model_dump(mode="json") for item in items]
    _atomic_write_json(ACTIVE_DISPATCHES_PATH, payload)


def append_active_dispatch(item: ActiveDispatch) -> None:
    """Append a single dispatch to active_dispatches.json."""
    items = read_active_dispatches()
    items.append(item)
    write_active_dispatches(items)


# ---------------------------------------------------------------------------
# loops.json
# ---------------------------------------------------------------------------

LOOPS_PATH: Path = STATE_DIR / "loops.json"


def read_loops() -> list[LoopEntry]:
    """Read loops.json; return empty list when missing."""
    if not LOOPS_PATH.exists():
        return []
    try:
        with LOOPS_PATH.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise StateFileCorruptError(LOOPS_PATH) from exc
    if not isinstance(raw, list):
        raise StateFileCorruptError(LOOPS_PATH)
    try:
        return [LoopEntry.model_validate(item) for item in raw]
    except Exception as exc:
        raise StateFileCorruptError(LOOPS_PATH) from exc


def write_loops(items: list[LoopEntry]) -> None:
    """Overwrite loops.json atomically."""
    payload = [item.model_dump(mode="json") for item in items]
    _atomic_write_json(LOOPS_PATH, payload)


# ---------------------------------------------------------------------------
# engine_health.json
# ---------------------------------------------------------------------------

ENGINE_HEALTH_PATH: Path = STATE_DIR / "engine_health.json"


def read_engine_health() -> dict[str, EngineHealth]:
    """Read engine_health.json; return empty dict when missing."""
    if not ENGINE_HEALTH_PATH.exists():
        return {}
    try:
        with ENGINE_HEALTH_PATH.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise StateFileCorruptError(ENGINE_HEALTH_PATH) from exc
    if not isinstance(raw, dict):
        raise StateFileCorruptError(ENGINE_HEALTH_PATH)
    try:
        return {
            name: EngineHealth.model_validate(item)
            for name, item in raw.items()
        }
    except Exception as exc:
        raise StateFileCorruptError(ENGINE_HEALTH_PATH) from exc


def write_engine_health(state: dict[str, EngineHealth]) -> None:
    """Overwrite engine_health.json atomically."""
    payload = {
        name: item.model_dump(mode="json")
        for name, item in state.items()
    }
    _atomic_write_json(ENGINE_HEALTH_PATH, payload)


def update_engine_health(name: str, patch: dict[str, Any]) -> None:
    """Partially update one engine entry and persist."""
    state = read_engine_health()
    current = state.get(name, EngineHealth())
    current_data = current.model_dump(mode="json")
    current_data.update(patch)
    state[name] = EngineHealth.model_validate(current_data)
    write_engine_health(state)
