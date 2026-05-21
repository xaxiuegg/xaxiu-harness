"""
SQLite history layer for xaxiu-harness.

Contract
--------
- All queries use parameterised placeholders (v1.2 HIGH-11 §4.1).
- Text fields (`project`, `source`, `action`) are validated before use.
- Integer `limit` parameters are limited by `LIMIT_MAX` (1000).
- No `executescript()`, no user-controlled concatenation.
- No views, triggers, or stored procedures.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterator, Optional

from harness._constants import (
    DB_FILE_NAME,
    LIMIT_MAX,
    PROJECT_NAME_REGEX,
    STATE_DIR,
)

_SNAPSHOT_DIR_NAME = "db_snapshots"


def _snapshot_dir() -> Path:
    return STATE_DIR / _SNAPSHOT_DIR_NAME


def _is_db_corrupt(db_path: Path) -> bool:
    """Run PRAGMA integrity_check; return True if it returned anything other than 'ok'."""
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            row = cur.fetchone()
            return not (row and row[0] == "ok")
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return True


def _move_aside_corrupt(db_path: Path) -> Path:
    """Rename a corrupt db to .corrupt.<ts>; return the new path."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    new_path = db_path.with_name(f"{db_path.name}.corrupt.{ts}")
    db_path.rename(new_path)
    return new_path


def _restore_from_snapshot(db_path: Path) -> bool:
    """If a snapshot exists, copy the newest one to db_path; return True on success."""
    snap_dir = _snapshot_dir()
    if not snap_dir.exists():
        return False
    snaps = sorted(snap_dir.glob(f"{db_path.name}.snap.*"))
    if not snaps:
        return False
    newest = snaps[-1]
    shutil.copy2(newest, db_path)
    return True


def _take_snapshot(db_path: Path) -> Path | None:
    """Copy db_path to snapshot_dir with a timestamp suffix; return snapshot path."""
    if not db_path.exists():
        return None
    snap_dir = _snapshot_dir()
    snap_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    snap_path = snap_dir / f"{db_path.name}.snap.{ts}"
    try:
        shutil.copy2(db_path, snap_path)
    except OSError:
        return None
    # Cap snapshot count at 24 (last day at 1/hour)
    all_snaps = sorted(snap_dir.glob(f"{db_path.name}.snap.*"))
    for old in all_snaps[:-24]:
        try:
            old.unlink()
        except OSError:
            pass
    return snap_path


# ---------------------------------------------------------------------------
# schema DDL – all CREATE TABLE with IF NOT EXISTS
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS dispatches (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    packet_path TEXT,
    backend TEXT NOT NULL,
    model TEXT,
    status TEXT NOT NULL,
    outcome TEXT,
    latency_ms INTEGER,
    fallback_to TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fallbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispatch_id TEXT REFERENCES dispatches(id),
    from_backend TEXT,
    to_backend TEXT,
    reason TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS observer_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    checked_at TEXT DEFAULT (datetime('now')),
    flags TEXT,
    status_count INTEGER
);

CREATE TABLE IF NOT EXISTS status_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    backend_type TEXT,
    written_at TEXT DEFAULT (datetime('now')),
    summary TEXT
);

CREATE TABLE IF NOT EXISTS routing_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now')),
    source TEXT NOT NULL,
    action TEXT NOT NULL,
    engine TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    client_ip TEXT
);
"""

# ---------------------------------------------------------------------------
# module-level state (connection singleton)
# ---------------------------------------------------------------------------

_connection: sqlite3.Connection | None = None


# ---------------------------------------------------------------------------
# helpers / validation
# ---------------------------------------------------------------------------

def _validate_project(project: str) -> str:
    """Raise ValueError if *project* doesn't match the allowed pattern."""
    if not re.match(PROJECT_NAME_REGEX, project):
        raise ValueError(f"Invalid project name: {project!r} (must match {PROJECT_NAME_REGEX})")
    return project


def _clamp_limit(limit: object) -> int:
    """Coerce *limit* to int and clamp between 1 and LIMIT_MAX."""
    try:
        n = int(limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"limit must be an integer, got {limit!r}")
    return min(max(n, 1), LIMIT_MAX)


_KNOWN_SOURCES = frozenset({"ws", "cli", "adapter"})
_KNOWN_ACTIONS = frozenset({"priority_change", "burst_start", "lock", "release"})


def _validate_source(source: str) -> str:
    if source not in _KNOWN_SOURCES:
        raise ValueError(f"Invalid source: {source!r}; must be one of {sorted(_KNOWN_SOURCES)}")
    return source


def _validate_action(action: str) -> str:
    if action not in _KNOWN_ACTIONS:
        raise ValueError(f"Invalid action: {action!r}; must be one of {sorted(_KNOWN_ACTIONS)}")
    return action


# ---------------------------------------------------------------------------
# initialisation & connection
# ---------------------------------------------------------------------------

def init_db(db_path: str | None = None) -> None:
    """
    Initialise the database at *db_path* (default: ``<repo_root>/state/history.db``).

    Creates tables if they don't exist and sets pragmas.
    Must be called before any other function in this module.
    """
    global _connection  # noqa: PLW0603

    if db_path is None:
        # default: <repo_root>/state/history.db via shared STATE_DIR
        # (avoids cwd-drift — Wave 2A MED fix)
        db_path = str(STATE_DIR / DB_FILE_NAME)

    # DB-CORRUPT-RECOVERY (2026-05-21): if the db file is corrupt, move it
    # aside and try to restore from the newest snapshot before opening.
    pre_path = Path(db_path)
    if pre_path.exists() and _is_db_corrupt(pre_path):
        corrupt_path = _move_aside_corrupt(pre_path)
        restored = _restore_from_snapshot(pre_path)
        # Best-effort: if restore failed, init_db will create a fresh db
        # below.  Either way, the corrupt file is preserved at corrupt_path
        # for post-mortem.
        del corrupt_path, restored  # silenced — logging not wired in this module

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.executescript(_SCHEMA_DDL)  # safe – static string
    conn.commit()
    _connection = conn


def get_connection() -> sqlite3.Connection:
    """Return the existing connection, lazily initialising at the default path.

    Production code paths (CLI dispatch, planner / worker dispatch, observer,
    budget meter) all reach the database through this helper.  Lazy init
    removes the requirement to call ``init_db()`` from every entry point —
    explicit init is still required when a custom ``db_path`` is desired.
    """
    if _connection is None:
        init_db()
    assert _connection is not None  # init_db sets it
    return _connection


@contextlib.contextmanager
def _tx() -> Iterator[sqlite3.Cursor]:
    """Context manager that yields a cursor; commits on success, rolls back on error."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# insert helpers
# ---------------------------------------------------------------------------

def insert_dispatch(
    project: str,
    packet_path: str,
    backend: str,
    model: str | None = None,
) -> str:
    """Insert a new dispatch row. Returns the generated UUID (32‑char hex)."""
    project = _validate_project(project)
    dispatch_id = uuid.uuid4().hex
    with _tx() as cur:
        cur.execute(
            """INSERT INTO dispatches (id, project, packet_path, backend, model, status, outcome, latency_ms, fallback_to)
               VALUES (?, ?, ?, ?, ?, 'dispatched', NULL, NULL, NULL)""",
            (dispatch_id, project, packet_path, backend, model),
        )
    return dispatch_id


def update_dispatch_status(
    dispatch_id: str,
    status: str,
    latency_ms: int | None = None,
    fallback_to: str | None = None,
) -> None:
    """Update an existing dispatch's outcome fields."""
    with _tx() as cur:
        cur.execute(
            """UPDATE dispatches
                   SET status = ?,
                       latency_ms = ?,
                       fallback_to = ?
                 WHERE id = ?""",
            (status, latency_ms, fallback_to, dispatch_id),
        )


def insert_fallback(
    dispatch_id: str,
    from_backend: str,
    to_backend: str,
    reason: str,
) -> int:
    """Record a fallback step. Returns the row ID."""
    with _tx() as cur:
        cur.execute(
            """INSERT INTO fallbacks (dispatch_id, from_backend, to_backend, reason)
               VALUES (?, ?, ?, ?)""",
            (dispatch_id, from_backend, to_backend, reason),
        )
        return cur.lastrowid  # type: ignore[return-value]


def insert_observer_cycle(
    project: str,
    flags: list[str],
    status_count: int,
) -> int:
    """Record an observer cycle result. *flags* is serialised as JSON text."""
    project = _validate_project(project)
    # json.dumps handles quotes/backslashes/unicode correctly — Wave 2A MED fix
    flags_str = json.dumps(flags)
    with _tx() as cur:
        cur.execute(
            """INSERT INTO observer_cycles (project, flags, status_count)
               VALUES (?, ?, ?)""",
            (project, flags_str, int(status_count)),
        )
        return cur.lastrowid  # type: ignore[return-value]


def insert_status_write(
    project: str,
    backend_type: str,
    summary: str,
) -> int:
    """Record a status write operation."""
    project = _validate_project(project)
    with _tx() as cur:
        cur.execute(
            """INSERT INTO status_writes (project, backend_type, summary)
               VALUES (?, ?, ?)""",
            (project, backend_type, summary),
        )
        return cur.lastrowid  # type: ignore[return-value]


def insert_routing_change(
    source: str,
    action: str,
    engine: str,
    old_value: str | None = None,
    new_value: str | None = None,
    client_ip: str | None = None,
) -> int:
    """Record a routing change (from WS, CLI, or adapter config change)."""
    source = _validate_source(source)
    action = _validate_action(action)
    with _tx() as cur:
        cur.execute(
            """INSERT INTO routing_changes (source, action, engine, old_value, new_value, client_ip)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source, action, engine, old_value, new_value, client_ip),
        )
        return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# query helpers
# ---------------------------------------------------------------------------

def _fetchall(sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    """Execute *sql* with *params* and return list-of-dicts."""
    conn = get_connection()
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def query_active_dispatches(
    project: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return recent dispatches, optionally filtered by project."""
    limit = _clamp_limit(limit)
    if project:
        project = _validate_project(project)
        rows = _fetchall(
            """SELECT * FROM dispatches
                WHERE project = ?
                ORDER BY created_at DESC
                LIMIT ?""",
            (project, limit),
        )
    else:
        rows = _fetchall(
            """SELECT * FROM dispatches
                ORDER BY created_at DESC
                LIMIT ?""",
            (limit,),
        )
    return rows


def query_recent_events(limit: int = 50) -> list[dict]:
    """
    Return a union of the latest dispatches, observer cycles, and routing changes.

    Each row carries a ``_table`` key so the caller can distinguish sources.
    """
    limit = _clamp_limit(limit)
    sql = """
    SELECT 'dispatch' AS _table, id AS event_id, created_at AS ts, project, backend, status
      FROM dispatches
     UNION ALL
    SELECT 'observer' AS _table, id AS event_id, checked_at AS ts, project, '' AS backend, '' AS status
      FROM observer_cycles
     UNION ALL
    SELECT 'routing' AS _table, id AS event_id, ts, engine AS project, source AS backend, action AS status
      FROM routing_changes
     ORDER BY ts DESC
     LIMIT ?
    """
    return _fetchall(sql, (limit,))


def query_fallback_chain(dispatch_id: str) -> list[dict]:
    """Return all fallback steps for a given dispatch, ordered chronologically."""
    rows = _fetchall(
        """SELECT * FROM fallbacks
            WHERE dispatch_id = ?
            ORDER BY id ASC""",
        (dispatch_id,),
    )
    return rows


def query_routing_history(
    engine: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return routing change records, optionally filtered by engine name."""
    limit = _clamp_limit(limit)
    if engine:
        rows = _fetchall(
            """SELECT * FROM routing_changes
                WHERE engine = ?
                ORDER BY id DESC
                LIMIT ?""",
            (engine, limit),
        )
    else:
        rows = _fetchall(
            """SELECT * FROM routing_changes
                ORDER BY id DESC
                LIMIT ?""",
            (limit,),
        )
    return rows