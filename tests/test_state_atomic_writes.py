"""W9-STATE-ATOMIC-WRITES: regression tests for the canonical
atomic_write_json helper + its callers.

W8 hit a load-bearing schema bug because a Pydantic validation
error was silently swallowed in the dispatch path.  M10 flagged
"silent state corruption is real" — multiple modules cloned the
tempfile + fsync + os.replace dance with subtle differences;
W9 consolidates them all behind one helper that:

  (a) writes to a temp file first
  (b) fsyncs before close
  (c) atomically renames over the target
  (d) raises StateFileCorruptError on serialization failure
  (e) cleans up the temp file on any error
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from harness.state.files import (
    StateFileCorruptError,
    atomic_write_json,
    atomic_write_yaml,
)


# -- atomic_write_json happy path -----------------------------------------


def test_atomic_write_json_creates_file_with_payload(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"a": 1, "b": [2, 3]}, set_mode_0600=False)
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": [2, 3]}


def test_atomic_write_json_overwrites_existing(tmp_path):
    target = tmp_path / "state.json"
    target.write_text('{"existing": "old"}', encoding="utf-8")
    atomic_write_json(target, {"new": "data"}, set_mode_0600=False)
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": "data"}


def test_atomic_write_json_outside_state_dir_uses_path_parent(tmp_path):
    """Path outside STATE_DIR: temp file goes in path.parent so the
    atomic rename stays on the same filesystem."""
    subdir = tmp_path / "deep" / "nested"
    target = subdir / "state.json"
    atomic_write_json(target, {"k": "v"}, set_mode_0600=False)
    assert target.exists()
    # No leftover .tmp files in the subdir
    leftovers = list(subdir.glob("*.tmp"))
    assert leftovers == []


# -- StateFileCorruptError on serialization failure -----------------------


def test_atomic_write_json_raises_StateFileCorruptError_on_non_serializable(tmp_path):
    target = tmp_path / "state.json"
    non_serializable = {"obj": object()}  # not JSON-able
    with pytest.raises(StateFileCorruptError) as exc_info:
        atomic_write_json(target, non_serializable, set_mode_0600=False)
    assert exc_info.value.path == target
    # Chained from TypeError
    assert isinstance(exc_info.value.__cause__, TypeError)


def test_atomic_write_json_leaves_target_untouched_on_serialization_failure(tmp_path):
    """Critical safety property: existing file must NOT be corrupted
    by a failed write attempt."""
    target = tmp_path / "state.json"
    target.write_text('{"original": "data"}', encoding="utf-8")
    with pytest.raises(StateFileCorruptError):
        atomic_write_json(target, {"bad": object()}, set_mode_0600=False)
    # Original content survives
    assert json.loads(target.read_text(encoding="utf-8")) == {"original": "data"}


def test_atomic_write_json_cleans_up_temp_file_on_failure(tmp_path):
    """No half-written temp files left behind after a failed write."""
    target = tmp_path / "state.json"
    with pytest.raises(StateFileCorruptError):
        atomic_write_json(target, {"bad": object()}, set_mode_0600=False)
    # No .tmp leftover in tmp_path
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], f"Temp file leaked after failed write: {leftovers}"


# -- Kill-during-write simulation -----------------------------------------


def test_atomic_write_json_kill_during_write_preserves_original(tmp_path):
    """Simulate a kill (mock json.dump to raise mid-write).
    The original file content MUST be preserved + temp file cleaned up.
    This is the W9 spec's "kill-during-write integration test"."""
    target = tmp_path / "state.json"
    target.write_text('{"committed": "value"}', encoding="utf-8")

    def _simulate_kill(*args, **kwargs):
        # Raise after a few bytes are written but before fsync
        raise KeyboardInterrupt("simulated kill")

    with patch("harness.state.files.json.dump", side_effect=_simulate_kill):
        with pytest.raises(KeyboardInterrupt):
            atomic_write_json(target, {"new": "value"}, set_mode_0600=False)

    # Original file uncorrupted
    assert json.loads(target.read_text(encoding="utf-8")) == {"committed": "value"}
    # No .tmp left over
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_json_oserror_at_tempfile_raises_StateFileCorrupt(tmp_path, monkeypatch):
    """If we can't even create a temp file (disk full, perms), raise
    the typed exception so callers see a recognizable error."""
    target = tmp_path / "state.json"

    def _fake_mkstemp(*args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr("harness.state.files.tempfile.mkstemp", _fake_mkstemp)
    with pytest.raises(StateFileCorruptError) as exc_info:
        atomic_write_json(target, {"a": 1}, set_mode_0600=False)
    assert exc_info.value.path == target


# -- atomic_write_yaml parity ---------------------------------------------


def test_atomic_write_yaml_creates_yaml_file(tmp_path):
    target = tmp_path / "config.yaml"
    atomic_write_yaml(target, {"key": "value", "nested": {"a": 1}})
    assert target.exists()
    import yaml as _y

    assert _y.safe_load(target.read_text(encoding="utf-8")) == {
        "key": "value",
        "nested": {"a": 1},
    }


# -- Delegation: heartbeat + observer use the canonical helper ------------


def test_heartbeat_atomic_write_delegates_to_canonical(tmp_path, monkeypatch):
    """heartbeat._atomic_write should call state.files.atomic_write_json
    (W9-STATE-ATOMIC-WRITES consolidation)."""
    from harness import heartbeat as _hb

    called: list[tuple] = []
    original = atomic_write_json

    def _capture(path, data, *, set_mode_0600=True):
        called.append((str(path), data, set_mode_0600))
        return original(path, data, set_mode_0600=set_mode_0600)

    monkeypatch.setattr("harness.state.files.atomic_write_json", _capture)
    target = tmp_path / "heartbeat.json"
    _hb._atomic_write(target, {"phase": "alive"})
    assert called, "heartbeat._atomic_write did not delegate"
    assert called[0][0] == str(target)
    assert called[0][2] is False  # heartbeat sets its own 0644


# PATH-A-TRIM 2026-05-29: test_observer_state_atomic_write_delegates_to_canonical
# removed — the observer.state module it exercised was deleted.


def test_reliability_digest_publish_uses_atomic_write(tmp_path, monkeypatch):
    """engines.reliability.publish_digest was a raw write_text + json.dumps;
    now routes through atomic_write_json."""
    from harness.engines import reliability as _rel

    called: list = []
    original = atomic_write_json

    def _capture(path, data, *, set_mode_0600=True):
        called.append(str(path))
        return original(path, data, set_mode_0600=set_mode_0600)

    monkeypatch.setattr("harness.state.files.atomic_write_json", _capture)
    # publish() calls aggregate_campaigns internally; stub it to
    # return a minimal digest so the test focuses on the write path.
    out = tmp_path / "digest.json"

    def _fake_aggregate(coverage_dir=None):
        return _rel.ReliabilityDigest(
            generated_at="2026-05-24T00:00:00+00:00",
            source_campaigns=["test"],
            notes=[],
            ranking=[],
        )

    monkeypatch.setattr(_rel, "aggregate_campaigns", _fake_aggregate)
    _rel.publish(out_path=out)
    assert called == [str(out)]
    assert out.exists()
