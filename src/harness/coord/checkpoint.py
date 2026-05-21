"""Worker checkpoint read/write helpers."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    worker_id: str = Field(pattern=r"^worker-\d+$")
    run_id: str = Field(min_length=1)
    last_completed_step_id: str | None = None
    last_completed_step_index: int = Field(ge=-1, default=-1)
    files_modified: list[str] = Field(default_factory=list, max_length=50)
    tests_passed: bool = False
    tests_summary: str = ""
    elapsed_seconds: int = Field(ge=0, default=0)
    commit_sha: str | None = None
    state: Literal["pending", "in_progress", "completed", "failed"] = "in_progress"
    updated_at: str = ""


def read_checkpoint(path: Path) -> Checkpoint | None:
    """Read a worker checkpoint JSON file."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return Checkpoint.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_checkpoint(path: Path, ckpt: Checkpoint) -> None:
    """Atomically write *ckpt* to *path* via temp-file + replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not ckpt.updated_at:
        ckpt = ckpt.model_copy(update={"updated_at": now_iso()})
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
