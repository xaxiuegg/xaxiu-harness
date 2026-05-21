"""Boundary tests for src/harness/state/jsonl_log.py.

Wave B/2.state-jsonl — pushes coverage from 22 % to >60 %.
"""

import builtins
import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from harness._constants import STATE_DIR
from harness.errors import SchemaViolation
from harness.state import jsonl_log


@pytest.fixture(autouse=True)
def _patch_state_dir(monkeypatch, tmp_path):
    """Redirect STATE_DIR to a temporary directory for every test."""
    monkeypatch.setattr(jsonl_log, "STATE_DIR", str(tmp_path))


# ---------------------------------------------------------------------------
# 1. write_log_entry happy path
# ---------------------------------------------------------------------------

def test_write_log_entry_happy_path(tmp_path):
    jsonl_log.write_log_entry(
        project="test-project",
        packet_path="/path/to/packet.md",
        backend="kimi",
        model="kimi-model",
        outcome="success",
        latency_ms=123,
        fallback_to=None,
    )

    log_file = tmp_path / jsonl_log.LOG_FILE_NAME
    assert log_file.exists()

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert set(entry.keys()) == {
        "timestamp",
        "project",
        "packet_path",
        "backend",
        "model",
        "outcome",
        "latency_ms",
        "fallback_to",
    }
    assert entry["project"] == "test-project"
    assert entry["packet_path"] == "/path/to/packet.md"
    assert entry["backend"] == "kimi"
    assert entry["model"] == "kimi-model"
    assert entry["outcome"] == "success"
    assert entry["latency_ms"] == 123
    assert entry["fallback_to"] is None

    # timestamp is a valid ISO-8601 string
    assert isinstance(entry["timestamp"], str)
    datetime.fromisoformat(entry["timestamp"])


# ---------------------------------------------------------------------------
# 2-4. write_log_entry rejects invalid fields
# ---------------------------------------------------------------------------

def test_write_log_entry_rejects_bad_outcome(tmp_path):
    with pytest.raises(SchemaViolation) as exc_info:
        jsonl_log.write_log_entry(
            project="test-project",
            packet_path="/path/to/packet.md",
            backend="kimi",
            model=None,
            outcome="not_a_real_outcome",
            latency_ms=0,
            fallback_to=None,
        )
    assert "outcome" in str(exc_info.value)
    assert exc_info.value.level == 4


def test_write_log_entry_rejects_bad_backend(tmp_path):
    with pytest.raises(SchemaViolation) as exc_info:
        jsonl_log.write_log_entry(
            project="test-project",
            packet_path="/path/to/packet.md",
            backend="not_a_backend",
            model=None,
            outcome="success",
            latency_ms=0,
            fallback_to=None,
        )
    assert "backend" in str(exc_info.value)
    assert exc_info.value.level == 4


def test_write_log_entry_rejects_bad_project_name(tmp_path):
    with pytest.raises(SchemaViolation) as exc_info:
        jsonl_log.write_log_entry(
            project="Invalid Project Name!",
            packet_path="/path/to/packet.md",
            backend="kimi",
            model=None,
            outcome="success",
            latency_ms=0,
            fallback_to=None,
        )
    assert "project" in str(exc_info.value)
    assert exc_info.value.level == 4


# ---------------------------------------------------------------------------
# 5-6. _redact behaviour
# ---------------------------------------------------------------------------

def test_redact_matches_all_five_patterns():
    dirty = (
        "sk-abcdefghijklmnopqrstuvwxyz123456 "
        "Bearer super_secret_token "
        'api_key="abcdef1234567890" '
        "ms-abcdefghijklmnopqrstuvwxyz123456 "
        "deepseek-abcdefghijklmnopqrstuvwxyz123456"
    )
    cleaned = jsonl_log._redact(dirty)
    assert cleaned is not None
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in cleaned
    assert "Bearer super_secret_token" not in cleaned
    assert 'api_key="abcdef1234567890"' not in cleaned
    assert "ms-abcdefghijklmnopqrstuvwxyz123456" not in cleaned
    assert "deepseek-abcdefghijklmnopqrstuvwxyz123456" not in cleaned
    assert cleaned.count("[REDACTED]") == 5


def test_redact_leaves_clean_text_alone():
    assert jsonl_log._redact("Hello world") == "Hello world"


# ---------------------------------------------------------------------------
# 7-8. rotate_if_needed
# ---------------------------------------------------------------------------

def test_rotate_if_needed_noop_below_threshold(tmp_path):
    log_file = tmp_path / jsonl_log.LOG_FILE_NAME
    log_file.write_text("small content\n", encoding="utf-8")

    # Ensure jsonl_log sees the file via patched STATE_DIR
    jsonl_log.rotate_if_needed()

    assert log_file.exists()
    assert log_file.read_text(encoding="utf-8") == "small content\n"
    assert not list(tmp_path.glob("*.gz"))


def test_rotate_if_needed_rotates_at_100mb(tmp_path):
    log_file = tmp_path / jsonl_log.LOG_FILE_NAME
    log_file.write_text("x" * 100, encoding="utf-8")

    # Lower threshold so the 100-byte file triggers rotation.
    with patch.object(jsonl_log, "ROTATION_SIZE_BYTES", 50):
        jsonl_log.rotate_if_needed()

    suffix = datetime.now(timezone.utc).strftime("%Y-%m")
    rotated = tmp_path / f"engine_performance_log.{suffix}.jsonl.gz"
    assert rotated.exists(), f"Expected {rotated.name} in {list(tmp_path.iterdir())}"

    # Verify gzip content includes original payload
    with gzip.open(rotated, "rt", encoding="utf-8") as gz:
        assert gz.read() == "x" * 100

    # Original file should be empty after rotation
    assert log_file.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# 9. Atomic append — opened in "ab" mode
# ---------------------------------------------------------------------------

def test_atomic_append_opens_in_ab_mode(tmp_path):
    captured_modes = []
    real_open = builtins.open

    def tracking_open(file, mode="r", *args, **kwargs):
        captured_modes.append(mode)
        return real_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=tracking_open):
        jsonl_log.write_log_entry(
            project="test-project",
            packet_path="/path/to/packet.md",
            backend="kimi",
            model=None,
            outcome="success",
            latency_ms=0,
            fallback_to=None,
        )

    assert "ab" in captured_modes


# ---------------------------------------------------------------------------
# 10. read_recent_entries — observability primitive for dashboard + supervisors
# ---------------------------------------------------------------------------

def test_read_recent_entries_newest_first_with_limit_and_skips_blanks(tmp_path):
    """read_recent_entries must: return [] when file absent, skip blank/garbage
    lines, return newest-first, and clamp limit. Used by dashboard + supervisors."""
    # File absent -> []
    assert jsonl_log.read_recent_entries() == []

    # Write 3 valid entries (oldest -> newest) plus blanks and a garbage line.
    log_file = tmp_path / jsonl_log.LOG_FILE_NAME
    log_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"timestamp": "t1", "backend": "kimi", "outcome": "success"}),
        "",  # blank — should be skipped
        "not-json{",  # garbage — should be skipped
        json.dumps({"timestamp": "t2", "backend": "deepseek", "outcome": "success"}),
        json.dumps({"timestamp": "t3", "backend": "kimi", "outcome": "fail"}),
    ]
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Default limit returns all 3 valid, newest-first.
    out = jsonl_log.read_recent_entries()
    assert [e["timestamp"] for e in out] == ["t3", "t2", "t1"]

    # limit=1 returns only newest.
    assert [e["timestamp"] for e in jsonl_log.read_recent_entries(limit=1)] == ["t3"]

    # limit=0 clamps to >=1 (one entry, newest).
    assert len(jsonl_log.read_recent_entries(limit=0)) == 1
