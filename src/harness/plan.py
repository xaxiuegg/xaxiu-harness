"""W13-HARNESS-PLAN-VERB: load + render the active strategic plan.

The plan is a hand-maintained Markdown file at ``coord/CURRENT_PLAN.md``
distilled from the most recent strategic planning panel.  This module
is the boundary between the file-on-disk and the CLI/SDK surfaces that
need to display it.

Design choices:
  - Plain Markdown, not JSON — humans update it by hand; agents read
    it as narrative text.
  - One canonical location (``<repo_root>/coord/CURRENT_PLAN.md``).
    Override via the ``HARNESS_PLAN_PATH`` env var for testing or for
    pointing at a project-specific plan from outside the harness repo.
  - ``load_current_plan()`` always returns a dict — never raises on
    missing file.  Caller decides how to render "no plan yet."
  - Designed to be cheap: pure file read, no parsing.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Default location relative to the repo root.  Operator may override
# with the ``HARNESS_PLAN_PATH`` env var.
DEFAULT_PLAN_RELPATH = Path("coord") / "CURRENT_PLAN.md"


def _repo_root() -> Path:
    """Resolve the harness repo root.

    Mirrors the heuristic from :mod:`harness._constants` — look for
    a ``pyproject.toml`` walking up from this file's location.
    """
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        if (ancestor / "pyproject.toml").is_file():
            return ancestor
    # Fallback: current working dir.
    return Path.cwd()


def plan_path(override: Path | str | None = None) -> Path:
    """Resolve the plan file path.

    Precedence:
      1. Explicit ``override`` argument
      2. ``HARNESS_PLAN_PATH`` env var
      3. ``<repo_root>/coord/CURRENT_PLAN.md``
    """
    if override is not None:
        return Path(override).expanduser().resolve()
    env = os.environ.get("HARNESS_PLAN_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return (_repo_root() / DEFAULT_PLAN_RELPATH).resolve()


def load_current_plan(override: Path | str | None = None) -> dict[str, Any]:
    """Load the active plan as a dict suitable for CLI / SDK display.

    Returned shape (always returns a dict, never raises):

        {
          "path": "<absolute path as str>",
          "exists": bool,
          "last_modified_iso": "2026-05-25T05:12:34+00:00" | None,
          "body_chars": int,         # 0 when exists=False
          "body": str,                # "" when exists=False
        }

    Designed so the caller can branch on ``exists`` and render either
    the body or a "no plan found" message — no exception handling
    needed in the common case.
    """
    path = plan_path(override)
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "last_modified_iso": None,
            "body_chars": 0,
            "body": "",
        }
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        # Permission / IO error — treat as "exists but unreadable"
        return {
            "path": str(path),
            "exists": True,
            "last_modified_iso": None,
            "body_chars": 0,
            "body": f"<error reading plan: {exc}>",
        }
    try:
        mtime = path.stat().st_mtime
        mtime_iso = datetime.fromtimestamp(
            mtime, tz=timezone.utc,
        ).isoformat()
    except OSError:
        mtime_iso = None
    return {
        "path": str(path),
        "exists": True,
        "last_modified_iso": mtime_iso,
        "body_chars": len(body),
        "body": body,
    }
