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
