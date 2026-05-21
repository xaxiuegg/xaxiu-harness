"""Worker checkpoint read/write helpers."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    worker_id: str = Field(pattern=r"^worker-\d+$")
    run_id: str = Field(min_length=1)
    state: str = "in_progress"
    updated_at: str = ""
    last_completed_step_id: str | None = None
    last_completed_step_index: int = -1
    files_modified: list[str] = Field(default_factory=list)
    tests_passed: bool | None = None
    tests_summary: str = ""
    elapsed_seconds: int = 0


def read_checkpoint(path: Path) -> Checkpoint | None:
    """Read a worker checkpoint JSON file."""
    try:
        return Checkpoint.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def write_checkpoint(path: Path, ckpt: Checkpoint) -> None:
    """Atomically write *ckpt* to *path* via temp-file + replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not ckpt.updated_at:
        ckpt.updated_at = now_iso()
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".ckpt_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(ckpt.model_dump_json(indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
