"""Atomic read/write helpers for Coordinator RunState."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from harness.coord.schemas import RunState


def read_run_state(path: Path) -> RunState | None:
    """Read and validate a RunState JSON file."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return RunState.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_run_state(path: Path, state: RunState) -> None:
    """Atomically write *state* to *path* via temp-file + replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".runstate_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(state.model_dump_json(indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
