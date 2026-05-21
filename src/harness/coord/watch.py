"""Live-tail helpers for `harness coord watch`."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator


WATCH_POLL_SECONDS = 0.5


def _checkpoint_summary(ckpt_path: Path) -> dict | None:
    """Return a tiny dict describing the checkpoint, or None if unreadable."""
    try:
        data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "worker_id": data.get("worker_id"),
        "state": data.get("state"),
        "last_completed_step_id": data.get("last_completed_step_id"),
        "files_modified": data.get("files_modified") or [],
        "commit_sha": data.get("commit_sha"),
        "updated_at": data.get("updated_at"),
    }


def watch_run(run_dir: Path, *, poll_seconds: float = WATCH_POLL_SECONDS) -> Iterator[str]:
    """Yield human-readable event lines as the run progresses.

    Events come from:
      - run_state.json mtime changes      → "run_state -> <state>"
      - checkpoints/*.json mtime changes  → "worker-1: in_progress (step=s1)"
    Yields until the run state becomes terminal ('completed' / 'failed').
    """
    run_state_path = run_dir / "run_state.json"
    checkpoints_dir = run_dir / "checkpoints"

    last_state_mtime: float = 0.0
    last_ckpt_mtimes: dict[Path, float] = {}
    terminal_states = {"completed", "failed"}

    while True:
        # run_state change
        if run_state_path.exists():
            try:
                mtime = run_state_path.stat().st_mtime
            except OSError:
                mtime = last_state_mtime
            if mtime > last_state_mtime:
                last_state_mtime = mtime
                try:
                    data = json.loads(run_state_path.read_text(encoding="utf-8"))
                    state = data.get("state", "?")
                    yield f"run_state -> {state}"
                    if state in terminal_states:
                        return
                except (OSError, json.JSONDecodeError):
                    pass

        # checkpoint changes
        if checkpoints_dir.exists():
            for ckpt_path in sorted(checkpoints_dir.glob("*.json")):
                try:
                    mtime = ckpt_path.stat().st_mtime
                except OSError:
                    continue
                if mtime > last_ckpt_mtimes.get(ckpt_path, 0.0):
                    last_ckpt_mtimes[ckpt_path] = mtime
                    summary = _checkpoint_summary(ckpt_path)
                    if summary:
                        files = (
                            f" files={len(summary['files_modified'])}"
                            if summary.get("files_modified")
                            else ""
                        )
                        step = (
                            f" step={summary['last_completed_step_id']}"
                            if summary.get("last_completed_step_id")
                            else ""
                        )
                        yield (
                            f"{summary['worker_id']}: {summary['state']}{step}{files}"
                        )

        time.sleep(poll_seconds)
