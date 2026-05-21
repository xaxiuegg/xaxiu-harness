"""Tests for DISK-FULL-GUARD — STATUS.csv writes refuse below disk floor + SHA verify + .bak rotation."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.status.store import (
    _check_disk_space,
    _sha256_of,
    _MIN_FREE_BYTES,
    write_status,
)
from harness.status.schema import StatusRow


def _row(id_: str = "TEST-1") -> StatusRow:
    return StatusRow(
        id=id_,
        category="Production",
        title="t",
        status="queued",
        owner="Claude inline",
        effort="30 min",
        updated="2026-05-21",
        notes="",
    )


def test_check_disk_space_passes_when_enough_free(tmp_path: Path) -> None:
    _check_disk_space(tmp_path, needed_bytes=1024)  # 1KB; should pass


def test_check_disk_space_raises_when_insufficient(tmp_path: Path) -> None:
    fake_usage = type("U", (), {"free": 100, "total": 1000, "used": 900})()
    with patch("harness.status.store._shutil") if False else patch(
        "shutil.disk_usage", return_value=fake_usage,
    ):
        with pytest.raises(OSError) as exc:
            _check_disk_space(tmp_path, needed_bytes=10000)
    assert "insufficient disk space" in str(exc.value)


def test_check_disk_space_silently_ok_when_disk_usage_fails(tmp_path: Path) -> None:
    """If disk_usage raises, we don't block writes."""
    with patch("shutil.disk_usage", side_effect=OSError("can't stat")):
        # Should NOT raise
        _check_disk_space(tmp_path)


def test_write_status_creates_bak_on_existing_file(tmp_path: Path) -> None:
    """Second write rotates the previous successful file to <path>.bak."""
    csv_path = tmp_path / "STATUS.csv"
    write_status(csv_path, [_row("A")])
    first_content = csv_path.read_text(encoding="utf-8")
    write_status(csv_path, [_row("B")])
    bak = csv_path.with_suffix(csv_path.suffix + ".bak")
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == first_content


def test_write_status_first_time_no_bak_needed(tmp_path: Path) -> None:
    csv_path = tmp_path / "STATUS.csv"
    write_status(csv_path, [_row("A")])
    bak = csv_path.with_suffix(csv_path.suffix + ".bak")
    # No bak file the first time (nothing to back up)
    assert not bak.exists()


def test_write_status_refuses_when_low_disk(tmp_path: Path) -> None:
    csv_path = tmp_path / "STATUS.csv"
    fake_usage = type("U", (), {"free": 100, "total": 1000, "used": 900})()
    with patch("shutil.disk_usage", return_value=fake_usage):
        with pytest.raises(OSError) as exc:
            write_status(csv_path, [_row("A")])
    assert "insufficient disk space" in str(exc.value)


def test_sha256_of_matches_expected(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert _sha256_of(p) == expected


def test_write_status_detects_post_replace_corruption(tmp_path: Path) -> None:
    """If the post-replace SHA disagrees with the temp SHA, we raise + restore bak."""
    csv_path = tmp_path / "STATUS.csv"
    write_status(csv_path, [_row("A")])  # produces a .bak via the next call

    # Now write again — this time tamper with the file post-replace.
    # We do that by patching _sha256_of to return different values for
    # tmp vs post-replace.
    call_count = {"n": 0}

    def _alternating_sha(path: Path) -> str:
        call_count["n"] += 1
        return f"fake-sha-{call_count['n']}"

    with patch("harness.status.store._sha256_of", side_effect=_alternating_sha):
        with pytest.raises(OSError) as exc:
            write_status(csv_path, [_row("B")])
    assert "corruption detected" in str(exc.value)


def test_min_free_bytes_is_reasonable() -> None:
    """Sanity: floor is 10 MB, not negative/zero or absurdly large."""
    assert 1024 * 1024 <= _MIN_FREE_BYTES <= 1024 * 1024 * 1024
