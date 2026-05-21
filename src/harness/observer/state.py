"""Observer state file (observer-state.json) — Pydantic-typed atomic I/O.

Follows the same security rules as harness.state.files:
- atomic writes via temp file + fsync
- corrupted files raise a path-only message
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from harness._constants import _REPO_ROOT

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OBSERVER_DIR: Path = _REPO_ROOT / "coord" / "observer"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class ObserverState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    armed: bool = True
    paused: bool = False
    cadence_minutes: int = Field(default=60, ge=5)
    daily_retro_time: str = "23:00"
    last_cycle_at: str | None = None
    last_cycle_id: str | None = None
    total_cycles: int = 0
    flags_raised: int = 0
    flags_acknowledged: int = 0
    status: str = "uninitialized"
    installed_at: str | None = None


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

class _StateFileCorruptError(Exception):
    """Raised when observer-state.json is unreadable (path only in msg)."""

    def __init__(self, path: Path) -> None:
        super().__init__(str(path))
        self.path = path


def _observer_state_path(observer_dir: Path | None = None) -> Path:
    base = observer_dir or DEFAULT_OBSERVER_DIR
    return base / "observer-state.json"


def _atomic_write(path: Path, data: dict[str, object]) -> None:
    """Atomic JSON write with fsync and restricted permissions."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    # Best-effort 0600 on Windows (no-op except through ACLs).
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_state(observer_dir: Path | None = None) -> ObserverState:
    """Read observer state or return defaults if missing/corrupt."""
    path = _observer_state_path(observer_dir)
    if not path.exists():
        return ObserverState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ObserverState.model_validate(raw)
    except (json.JSONDecodeError, OSError) as exc:
        raise _StateFileCorruptError(path) from exc


def write_state(state: ObserverState, observer_dir: Path | None = None) -> None:
    """Write observer state atomically."""
    path = _observer_state_path(observer_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, state.model_dump(mode="json"))
