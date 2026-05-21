# DB-CORRUPT-RECOVERY — SQLite integrity_check + auto-restore from snapshot

## Goal

`history.db` is currently a single point of failure: a power-fail mid-write
or a partial-flush crash can leave it corrupt, and there's no automatic
recovery path.  This wave adds an integrity check at first connection and
a best-effort restore from the latest hourly snapshot if corrupt.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper functions in `src/harness/state/db.py`

ADD near the top of the file (after imports, before init_db):

```python
import shutil


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
```

### 2. Modify `init_db` to integrity-check + auto-restore

Find the existing `init_db` function.  At the very start of its body
(after the `db_path` default resolution, before `path = Path(db_path)`),
add:

```python
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
```

### 3. Tests

`tests/test_db_corrupt_recovery.py`:

```python
"""Tests for DB-CORRUPT-RECOVERY."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from harness.state import db as db_module


def test_is_corrupt_false_on_clean_db(tmp_path: Path) -> None:
    p = tmp_path / "fresh.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE x (id INTEGER);")
    conn.commit()
    conn.close()
    assert db_module._is_db_corrupt(p) is False


def test_is_corrupt_true_on_garbage(tmp_path: Path) -> None:
    p = tmp_path / "garbage.db"
    p.write_bytes(b"this is not a sqlite database\x00\x01\x02\x03" * 64)
    assert db_module._is_db_corrupt(p) is True


def test_move_aside_corrupt_renames(tmp_path: Path) -> None:
    p = tmp_path / "history.db"
    p.write_bytes(b"garbage")
    moved = db_module._move_aside_corrupt(p)
    assert not p.exists()
    assert moved.exists()
    assert ".corrupt." in moved.name


def test_take_snapshot_copies_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "STATE_DIR", tmp_path)
    p = tmp_path / "history.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE x (id INTEGER);")
    conn.commit()
    conn.close()
    snap = db_module._take_snapshot(p)
    assert snap is not None
    assert snap.exists()
    assert ".snap." in snap.name


def test_restore_from_snapshot_recovers_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "STATE_DIR", tmp_path)
    p = tmp_path / "history.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE x (id INTEGER);")
    conn.execute("INSERT INTO x VALUES (42);")
    conn.commit()
    conn.close()
    db_module._take_snapshot(p)
    # Now wipe the original; restore should bring it back
    p.unlink()
    ok = db_module._restore_from_snapshot(p)
    assert ok is True
    assert p.exists()
    conn = sqlite3.connect(str(p))
    row = conn.execute("SELECT id FROM x;").fetchone()
    conn.close()
    assert row == (42,)


def test_restore_returns_false_when_no_snapshots(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "STATE_DIR", tmp_path)
    p = tmp_path / "history.db"
    assert db_module._restore_from_snapshot(p) is False


def test_init_db_auto_recovers_corrupt_db(tmp_path: Path, monkeypatch) -> None:
    """init_db sees a corrupt file → moves aside → opens fresh."""
    monkeypatch.setattr(db_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(db_module, "_connection", None)
    db_path = tmp_path / "history.db"
    db_path.write_bytes(b"corrupt rubbish" * 32)
    # Should not raise — init_db moves aside + opens fresh
    db_module.init_db(db_path=str(db_path))
    # New (clean) db exists
    assert db_path.exists()
    # Corrupt file preserved with a .corrupt. suffix
    assert any(p.name.startswith("history.db.corrupt.") for p in tmp_path.iterdir())


def test_snapshot_count_capped_at_24(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "STATE_DIR", tmp_path)
    # Force the snapshot dir layout
    snap_dir = db_module._snapshot_dir()
    snap_dir.mkdir(parents=True, exist_ok=True)
    # Pre-create 30 fake snapshots
    p = tmp_path / "history.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE x (id INTEGER);")
    conn.commit()
    conn.close()
    for i in range(30):
        db_module._take_snapshot(p)
    snaps = sorted(snap_dir.glob("history.db.snap.*"))
    assert len(snaps) <= 24
```

## Acceptance

- `python -m pytest tests/test_db_corrupt_recovery.py` — green.
- Full suite stays green (must not break existing test_state_db.py).
- Corrupt db file is moved aside, not deleted (postmortem preserved).

## Constraints

- DO NOT modify the existing public init_db signature or behavior on a
  CLEAN db file.  The corrupt-recovery code path activates ONLY when
  `_is_db_corrupt` returns True.
- DO NOT touch tests/test_state_db.py.
- Snapshots stored under STATE_DIR/db_snapshots/.
- Stdlib only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
