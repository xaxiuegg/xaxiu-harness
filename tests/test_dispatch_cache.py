"""W11-DISPATCH-CACHE: tests for the content+adapter-hash keyed cache.

Per W11 plan acceptance:
  - Same-prompt-cached: identical (content, adapter) returns cached
  - Different-prompt-miss: changed packet content -> new entry
  - Adapter-edit-invalidates: same content but adapter file changed -> miss
  - TTL expiry: stored entry older than HARNESS_DISPATCH_CACHE_TTL_SEC -> miss
  - JSON-on-disk: cached payload is valid JSON
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from harness.engines import dispatch_cache as dc


# -- compute_cache_key ----------------------------------------------------


def test_compute_cache_key_format():
    """Key is `<content>__<adapter>` hex pairs."""
    k = dc.compute_cache_key("hello", None)
    assert "__" in k
    content_part, adapter_part = k.split("__", 1)
    assert len(content_part) == 16  # truncated SHA-256
    assert adapter_part == "noadapter"


def test_compute_cache_key_same_content_same_key():
    k1 = dc.compute_cache_key("packet body here", None)
    k2 = dc.compute_cache_key("packet body here", None)
    assert k1 == k2


def test_compute_cache_key_changed_content_differs(tmp_path):
    k1 = dc.compute_cache_key("body A", None)
    k2 = dc.compute_cache_key("body B", None)
    assert k1 != k2


def test_compute_cache_key_adapter_path_affects_key(tmp_path):
    """Same content, different adapter file -> different key."""
    adapter_a = tmp_path / "adapter_a.py"
    adapter_a.write_text("config = 'a'\n", encoding="utf-8")
    adapter_b = tmp_path / "adapter_b.py"
    adapter_b.write_text("config = 'b'\n", encoding="utf-8")
    k1 = dc.compute_cache_key("same content", adapter_a)
    k2 = dc.compute_cache_key("same content", adapter_b)
    assert k1 != k2


def test_compute_cache_key_adapter_edit_changes_hash(tmp_path):
    """Same path, content edited -> different adapter_hash component."""
    adapter = tmp_path / "adapter.py"
    adapter.write_text("v1 = True\n", encoding="utf-8")
    k1 = dc.compute_cache_key("same packet", adapter)
    # Edit the adapter
    adapter.write_text("v2 = True\n", encoding="utf-8")
    k2 = dc.compute_cache_key("same packet", adapter)
    assert k1 != k2


def test_compute_cache_key_missing_adapter_uses_marker(tmp_path):
    """Missing adapter file produces 'missing' hash, not crash."""
    k = dc.compute_cache_key("body", tmp_path / "no-such-adapter.py")
    assert "missing" in k


# -- store + lookup roundtrip ---------------------------------------------


def test_store_then_lookup_roundtrip(tmp_path):
    payload = {
        "success": True,
        "engine_used": "kimi",
        "text": "full response here",
        "tokens_used": 42,
    }
    key = "abc__def"
    written = dc.store(key, payload, project_root=tmp_path)
    assert written.exists()
    loaded = dc.lookup(key, project_root=tmp_path)
    assert loaded == payload


def test_lookup_misses_when_key_unknown(tmp_path):
    assert dc.lookup("never-stored", project_root=tmp_path) is None


def test_store_accepts_dataclass(tmp_path):
    """store() accepts a dataclass + auto-asdict()s it."""
    from harness.engines.dispatcher import DispatchResult
    r = DispatchResult(
        success=True, engine_used="kimi", fallback_chain=["kimi"],
        text="response", error=None, dispatch_id="abc",
    )
    key = "fromdc__test"
    dc.store(key, r, project_root=tmp_path)
    loaded = dc.lookup(key, project_root=tmp_path)
    assert loaded["success"] is True
    assert loaded["engine_used"] == "kimi"


def test_store_creates_cache_dir(tmp_path):
    """First-time store creates .harness/dispatched/ if missing."""
    assert not (tmp_path / ".harness" / "dispatched").exists()
    dc.store("key1", {"x": 1}, project_root=tmp_path)
    assert (tmp_path / ".harness" / "dispatched").is_dir()


def test_store_writes_valid_json(tmp_path):
    """W11 acceptance: cache file is valid JSON on disk."""
    dc.store("key2", {"nested": {"data": [1, 2, 3]}}, project_root=tmp_path)
    path = dc.cache_path_for("key2", tmp_path)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["nested"]["data"] == [1, 2, 3]


# -- TTL expiry ----------------------------------------------------------


def test_lookup_returns_none_for_expired_entry(tmp_path, monkeypatch):
    """Entry older than ttl_sec -> miss + deleted."""
    dc.store("aged", {"x": "y"}, project_root=tmp_path)
    path = dc.cache_path_for("aged", tmp_path)
    assert path.exists()
    # Backdate mtime well past TTL
    old_mtime = time.time() - (DC_FAKE_OLD := 99999999)
    os.utime(path, (old_mtime, old_mtime))
    result = dc.lookup("aged", project_root=tmp_path, ttl_sec=60)
    assert result is None
    # And the expired file was cleaned up
    assert not path.exists()


def test_lookup_ttl_zero_means_no_expiry(tmp_path):
    dc.store("fresh", {"x": "y"}, project_root=tmp_path)
    path = dc.cache_path_for("fresh", tmp_path)
    # Backdate way in the past
    os.utime(path, (1, 1))
    # ttl_sec=0 means never expire
    result = dc.lookup("fresh", project_root=tmp_path, ttl_sec=0)
    assert result == {"x": "y"}


def test_ttl_seconds_reads_env(monkeypatch):
    monkeypatch.setenv("HARNESS_DISPATCH_CACHE_TTL_SEC", "120")
    assert dc._ttl_seconds() == 120


def test_ttl_seconds_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("HARNESS_DISPATCH_CACHE_TTL_SEC", "not-a-number")
    assert dc._ttl_seconds() == dc.DEFAULT_TTL_SEC


def test_ttl_seconds_negative_clamped_to_zero(monkeypatch):
    monkeypatch.setenv("HARNESS_DISPATCH_CACHE_TTL_SEC", "-100")
    assert dc._ttl_seconds() == 0


# -- Corrupted-cache handling -------------------------------------------


def test_lookup_drops_corrupted_entry(tmp_path):
    """Malformed JSON on disk -> miss + file removed (so next call repopulates)."""
    cdir = tmp_path / ".harness" / "dispatched"
    cdir.mkdir(parents=True)
    bad = cdir / "broken.json"
    bad.write_text("{not valid: json{", encoding="utf-8")
    result = dc.lookup("broken", project_root=tmp_path)
    assert result is None
    assert not bad.exists()  # cleaned up


# -- invalidate + clear_all ---------------------------------------------


def test_invalidate_removes_single_entry(tmp_path):
    dc.store("k1", {"x": 1}, project_root=tmp_path)
    dc.store("k2", {"y": 2}, project_root=tmp_path)
    assert dc.invalidate("k1", project_root=tmp_path) is True
    assert dc.lookup("k1", project_root=tmp_path) is None
    # Other entry untouched
    assert dc.lookup("k2", project_root=tmp_path) == {"y": 2}


def test_invalidate_returns_false_on_missing(tmp_path):
    assert dc.invalidate("never-stored", project_root=tmp_path) is False


def test_clear_all_deletes_all_entries(tmp_path):
    dc.store("k1", {"x": 1}, project_root=tmp_path)
    dc.store("k2", {"y": 2}, project_root=tmp_path)
    dc.store("k3", {"z": 3}, project_root=tmp_path)
    count = dc.clear_all(tmp_path)
    assert count == 3
    assert dc.lookup("k1", project_root=tmp_path) is None
    assert dc.lookup("k2", project_root=tmp_path) is None


def test_clear_all_on_missing_dir_is_no_op(tmp_path):
    """No exception when .harness/dispatched/ doesn't exist."""
    assert dc.clear_all(tmp_path / "nonexistent") == 0


# -- cache_stats --------------------------------------------------------


def test_cache_stats_empty_dir(tmp_path):
    stats = dc.cache_stats(tmp_path)
    assert stats == {"entries": 0, "total_bytes": 0}


def test_cache_stats_after_stores(tmp_path):
    dc.store("k1", {"x": "small"}, project_root=tmp_path)
    dc.store("k2", {"y": "a" * 1000}, project_root=tmp_path)
    stats = dc.cache_stats(tmp_path)
    assert stats["entries"] == 2
    assert stats["total_bytes"] > 1000


# -- Atomic write integration -------------------------------------------


def test_store_uses_atomic_write_when_available(tmp_path):
    """Store delegates to harness.state.files.atomic_write_json (W9 helper)."""
    dc.store("atomic-test", {"key": "value"}, project_root=tmp_path)
    path = dc.cache_path_for("atomic-test", tmp_path)
    assert path.exists()
    # No leftover .tmp files (proves the atomic helper cleaned up)
    leftovers = list((tmp_path / ".harness" / "dispatched").glob("*.tmp"))
    assert leftovers == []
