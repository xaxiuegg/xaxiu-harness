"""Tests for harness.coord.checkpoint."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from harness.coord.checkpoint import (
    Checkpoint,
    read_checkpoint,
    write_checkpoint,
    now_iso,
)


# ---------------------------------------------------------------------------
# Checkpoint model validation
# ---------------------------------------------------------------------------

def test_checkpoint_rejects_bad_worker_id_pattern() -> None:
    with pytest.raises(ValidationError):
        Checkpoint(
            worker_id="bad-id",
            run_id="20260520T220000-ab12",
        )


def test_checkpoint_accepts_valid_worker_id() -> None:
    ckpt = Checkpoint(
        worker_id="worker-1",
        run_id="20260520T220000-ab12",
    )
    assert ckpt.worker_id == "worker-1"
    assert ckpt.schema_version == 1
    assert ckpt.state == "in_progress"


def test_checkpoint_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Checkpoint(
            worker_id="worker-1",
            run_id="run-1",
            bonus_field="nope",
        )


def test_checkpoint_roundtrip_json() -> None:
    original = Checkpoint(
        worker_id="worker-1",
        run_id="20260520T220000-ab12",
        last_completed_step_id="step-2",
        last_completed_step_index=1,
        files_modified=["src/foo.py"],
        tests_passed=True,
        tests_summary="5p/0f/0s",
        elapsed_seconds=120,
        state="completed",
        updated_at="2026-05-20T22:00:00+00:00",
    )
    dumped = original.model_dump_json()
    restored = Checkpoint.model_validate_json(dumped)
    assert restored.worker_id == original.worker_id
    assert restored.last_completed_step_index == 1
    assert restored.state == "completed"


# ---------------------------------------------------------------------------
# read_checkpoint
# ---------------------------------------------------------------------------

def test_read_checkpoint_missing_returns_none(tmp_path: Path) -> None:
    assert read_checkpoint(tmp_path / "missing.json") is None


def test_read_checkpoint_corrupt_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("not-json{{{", encoding="utf-8")
    assert read_checkpoint(path) is None


def test_read_checkpoint_valid_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.json"
    original = Checkpoint(
        worker_id="worker-1",
        run_id="run-1",
        last_completed_step_index=2,
        state="failed",
    )
    write_checkpoint(path, original)
    restored = read_checkpoint(path)
    assert restored is not None
    assert restored.worker_id == "worker-1"
    assert restored.state == "failed"
    assert restored.last_completed_step_index == 2


# ---------------------------------------------------------------------------
# write_checkpoint
# ---------------------------------------------------------------------------

def test_write_checkpoint_creates_file_and_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "ckpt.json"
    ckpt = Checkpoint(worker_id="worker-1", run_id="run-1")
    write_checkpoint(nested, ckpt)
    assert nested.exists()
    restored = Checkpoint.model_validate_json(nested.read_text(encoding="utf-8"))
    assert restored.worker_id == "worker-1"


def test_write_checkpoint_auto_populates_updated_at(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.json"
    ckpt = Checkpoint(worker_id="worker-1", run_id="run-1", updated_at="")
    write_checkpoint(path, ckpt)
    restored = read_checkpoint(path)
    assert restored is not None
    assert restored.updated_at != ""
    # Should be a valid ISO timestamp
    assert "T" in restored.updated_at


def test_write_checkpoint_preserves_provided_updated_at(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.json"
    fixed_time = "2026-05-20T22:00:00+00:00"
    ckpt = Checkpoint(worker_id="worker-1", run_id="run-1", updated_at=fixed_time)
    write_checkpoint(path, ckpt)
    restored = read_checkpoint(path)
    assert restored is not None
    assert restored.updated_at == fixed_time


def test_write_checkpoint_atomic_write_contract(tmp_path: Path) -> None:
    """If os.replace fails, the original file must remain intact and temp cleaned up."""
    path = tmp_path / "ckpt.json"
    original_ckpt = Checkpoint(
        worker_id="worker-1",
        run_id="run-1",
        last_completed_step_index=0,
        updated_at="2026-05-20T21:00:00+00:00",
    )
    write_checkpoint(path, original_ckpt)
    assert path.exists()

    bad_ckpt = Checkpoint(
        worker_id="worker-1",
        run_id="run-1",
        last_completed_step_index=99,
        updated_at="2026-05-20T22:00:00+00:00",
    )

    with patch("harness.coord.checkpoint.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            write_checkpoint(path, bad_ckpt)

    # Original file intact
    restored = read_checkpoint(path)
    assert restored is not None
    assert restored.last_completed_step_index == 0
    # No lingering temp files
    temps = list(tmp_path.glob(".ckpt_*"))
    assert len(temps) == 0
