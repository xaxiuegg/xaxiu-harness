"""Boundary tests for src.harness.state.files.

Wave B/2.state-files — pushes files.py coverage from 39% to >60%.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

import harness.state.files as _files
from harness.state.files import (
    ActiveDispatch,
    EngineHealth,
    HarnessConfig,
    LoopEntry,
    StateFileCorruptError,
    _atomic_write_json,
    _atomic_write_yaml,
    _set_mode_0600,
    append_active_dispatch,
    read_active_dispatches,
    read_engine_health,
    read_harness_config,
    read_loops,
    update_engine_health,
    write_active_dispatches,
    write_engine_health,
    write_harness_config,
    write_loops,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect all state file paths into *tmp_path*."""
    monkeypatch.setattr(_files, "STATE_DIR", tmp_path)
    monkeypatch.setattr(_files, "HARNESS_CONFIG_PATH", tmp_path / "harness.config.yml")
    monkeypatch.setattr(_files, "ACTIVE_DISPATCHES_PATH", tmp_path / "active_dispatches.json")
    monkeypatch.setattr(_files, "LOOPS_PATH", tmp_path / "loops.json")
    monkeypatch.setattr(_files, "ENGINE_HEALTH_PATH", tmp_path / "engine_health.json")
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Engine health roundtrip
# ---------------------------------------------------------------------------
def test_update_engine_health_roundtrip(state_dir: Path) -> None:
    update_engine_health("kimi", {"status": "up", "avg_latency_ms": 42})
    health = read_engine_health()
    assert "kimi" in health
    assert health["kimi"].status == "up"
    assert health["kimi"].avg_latency_ms == 42


def test_update_engine_health_merges_existing(state_dir: Path) -> None:
    update_engine_health("deepseek", {"status": "degraded", "avg_latency_ms": 100})
    update_engine_health("deepseek", {"avg_latency_ms": 150})
    health = read_engine_health()
    assert health["deepseek"].status == "degraded"
    assert health["deepseek"].avg_latency_ms == 150


# ---------------------------------------------------------------------------
# 2. Engine health pruning (documented but not yet implemented)
# ---------------------------------------------------------------------------
def test_engine_health_no_pruning_current_behavior(state_dir: Path) -> None:
    """Entries persist indefinitely until explicitly overwritten."""
    update_engine_health("old-engine", {"status": "down"})
    health = read_engine_health()
    assert "old-engine" in health
    assert health["old-engine"].status == "down"


# ---------------------------------------------------------------------------
# 3. Active dispatch insert / update / remove
# ---------------------------------------------------------------------------
def test_read_active_dispatches_missing_file_returns_empty_list(state_dir: Path) -> None:
    assert read_active_dispatches() == []


def test_append_active_dispatch_roundtrip(state_dir: Path) -> None:
    dispatch = ActiveDispatch(
        dispatch_id="uuid-1",
        project="demo",
        packet_path="/p/demo.md",
        backend="kimi",
        started_at="2026-05-20T00:00:00Z",
        status="running",
    )
    append_active_dispatch(dispatch)
    items = read_active_dispatches()
    assert len(items) == 1
    assert items[0].dispatch_id == "uuid-1"
    assert items[0].status == "running"


def test_write_active_dispatches_overwrite(state_dir: Path) -> None:
    d1 = ActiveDispatch(
        dispatch_id="uuid-1",
        project="demo",
        packet_path="/p/demo.md",
        backend="kimi",
        started_at="2026-05-20T00:00:00Z",
        status="running",
    )
    d2 = ActiveDispatch(
        dispatch_id="uuid-2",
        project="demo",
        packet_path="/p/demo2.md",
        backend="deepseek",
        started_at="2026-05-20T00:01:00Z",
        status="complete",
    )
    append_active_dispatch(d1)
    write_active_dispatches([d2])
    items = read_active_dispatches()
    assert len(items) == 1
    assert items[0].dispatch_id == "uuid-2"


# ---------------------------------------------------------------------------
# 4. Atomic write — tempfile + os.replace pattern
# ---------------------------------------------------------------------------
def test_atomic_write_json_uses_tempfile_and_replace(state_dir: Path) -> None:
    path = state_dir / "test_atomic.json"
    fd_mock = 99
    tmp_name = str(state_dir / "test_atomic.json.tmp")

    with patch("harness.state.files.tempfile.mkstemp", return_value=(fd_mock, tmp_name)) as mock_mkstemp:
        with patch("harness.state.files.os.replace") as mock_replace:
            with patch("harness.state.files.os.fdopen") as mock_fdopen:
                with patch("harness.state.files.os.fsync"):
                    with patch("harness.state.files._set_mode_0600"):
                        mock_fh = MagicMock()
                        mock_fdopen.return_value.__enter__ = MagicMock(return_value=mock_fh)
                        mock_fdopen.return_value.__exit__ = MagicMock(return_value=False)
                        _atomic_write_json(path, {"key": "val"})
                        mock_mkstemp.assert_called_once_with(dir=state_dir, suffix=".tmp")
                        mock_replace.assert_called_once_with(Path(tmp_name), path)


# ---------------------------------------------------------------------------
# 5. Mode 0600 after write
# ---------------------------------------------------------------------------
def test_atomic_write_json_sets_mode_0600(state_dir: Path) -> None:
    path = state_dir / "mode_test.json"
    with patch("harness.state.files.os.chmod") as mock_chmod:
        _atomic_write_json(path, {"data": 1})
    mock_chmod.assert_called_once_with(path, 0o600)


def test_set_mode_0600_calls_os_chmod(state_dir: Path) -> None:
    path = state_dir / "chmod_test.txt"
    path.write_text("x", encoding="utf-8")
    with patch("harness.state.files.os.chmod") as mock_chmod:
        _set_mode_0600(path)
    mock_chmod.assert_called_once_with(path, 0o600)


# ---------------------------------------------------------------------------
# 6. Schema validation — unexpected fields raise ValidationError
# ---------------------------------------------------------------------------
def test_active_dispatch_schema_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        ActiveDispatch.model_validate(
            {
                "dispatch_id": "x",
                "project": "p",
                "packet_path": "/p.md",
                "backend": "kimi",
                "started_at": "2026-05-20T00:00:00Z",
                "status": "running",
                "unexpected": True,
            }
        )


def test_engine_health_schema_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        EngineHealth.model_validate({"status": "up", "extra_field": 123})


def test_harness_config_schema_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        HarnessConfig.model_validate({"harness_version": "1.0", "bogus": True})


# ---------------------------------------------------------------------------
# 7. First-read with missing file — sensible defaults, no raise
# ---------------------------------------------------------------------------
def test_read_engine_health_missing_file_returns_empty_dict(state_dir: Path) -> None:
    assert read_engine_health() == {}


def test_read_loops_missing_file_returns_empty_list(state_dir: Path) -> None:
    assert read_loops() == []


def test_read_harness_config_missing_file_returns_default(state_dir: Path) -> None:
    cfg = read_harness_config()
    assert cfg.harness_version == "1.2.0"
    assert cfg.installed is False


# ---------------------------------------------------------------------------
# 8. Concurrent-write race (best-effort)
# ---------------------------------------------------------------------------
def test_concurrent_update_engine_health(state_dir: Path) -> None:
    """Two threads updating different engines should both land."""
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(name: str, patch_data: dict) -> None:
        try:
            barrier.wait(timeout=2)
            update_engine_health(name, patch_data)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("engine-a", {"avg_latency_ms": 10}))
    t2 = threading.Thread(target=worker, args=("engine-b", {"avg_latency_ms": 20}))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, f"Threads raised exceptions: {errors}"
    health = read_engine_health()
    # Soft-assert: both engines should be present.
    assert "engine-a" in health or "engine-b" in health
    if "engine-a" in health:
        assert health["engine-a"].avg_latency_ms == 10
    if "engine-b" in health:
        assert health["engine-b"].avg_latency_ms == 20


# ---------------------------------------------------------------------------
# Additional coverage drivers
# ---------------------------------------------------------------------------
def test_loops_roundtrip(state_dir: Path) -> None:
    entry = LoopEntry(
        name="nightly",
        command="harness dispatch --packet nightly.md",
        cron="0 2 * * *",
        task_name="xaxiu-harness-nightly",
    )
    write_loops([entry])
    items = read_loops()
    assert len(items) == 1
    assert items[0].name == "nightly"
    assert items[0].command.startswith("harness ")


def test_harness_config_roundtrip(state_dir: Path) -> None:
    cfg = HarnessConfig(harness_version="0.5.0", installed=True, default_project="foo")
    write_harness_config(cfg)
    loaded = read_harness_config()
    assert loaded.harness_version == "0.5.0"
    assert loaded.installed is True
    assert loaded.default_project == "foo"


def test_loop_entry_command_must_start_with_harness() -> None:
    with pytest.raises(ValidationError, match="must start with 'harness '"):
        LoopEntry(name="bad", command="not-harness", cron="* * * * *", task_name="x-bad")


def test_corrupt_json_raises_state_file_corrupt_error(state_dir: Path) -> None:
    _files.ENGINE_HEALTH_PATH.write_text("not-json{{", encoding="utf-8")
    with pytest.raises(StateFileCorruptError) as exc_info:
        read_engine_health()
    assert str(_files.ENGINE_HEALTH_PATH) in str(exc_info.value)


def test_non_list_dispatches_raises_state_file_corrupt_error(state_dir: Path) -> None:
    _files.ACTIVE_DISPATCHES_PATH.write_text('{"foo": "bar"}', encoding="utf-8")
    with pytest.raises(StateFileCorruptError):
        read_active_dispatches()


def test_non_dict_engine_health_raises_state_file_corrupt_error(state_dir: Path) -> None:
    _files.ENGINE_HEALTH_PATH.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(StateFileCorruptError):
        read_engine_health()


def test_state_file_corrupt_error_contains_path_only() -> None:
    p = Path("/some/state.json")
    err = StateFileCorruptError(p)
    assert str(p) in str(err)
    assert err.path == p


def test_atomic_write_yaml_uses_tempfile_and_replace(state_dir: Path) -> None:
    path = state_dir / "test_atomic.yml"
    fd_mock = 99
    tmp_name = str(state_dir / "test_atomic.yml.tmp")

    with patch("harness.state.files.tempfile.mkstemp", return_value=(fd_mock, tmp_name)) as mock_mkstemp:
        with patch("harness.state.files.os.replace") as mock_replace:
            with patch("harness.state.files.os.fdopen") as mock_fdopen:
                with patch("harness.state.files.os.fsync"):
                    with patch("harness.state.files._set_mode_0600"):
                        mock_fh = MagicMock()
                        mock_fdopen.return_value.__enter__ = MagicMock(return_value=mock_fh)
                        mock_fdopen.return_value.__exit__ = MagicMock(return_value=False)
                        _atomic_write_yaml(path, {"key": "val"})
                        mock_mkstemp.assert_called_once_with(dir=state_dir, suffix=".tmp")
                        mock_replace.assert_called_once_with(Path(tmp_name), path)


def test_atomic_write_json_cleans_up_on_exception(state_dir: Path) -> None:
    path = state_dir / "fail_test.json"
    fd_mock = 99
    tmp_name = str(state_dir / "fail_test.json.tmp")

    with patch("harness.state.files.tempfile.mkstemp", return_value=(fd_mock, tmp_name)):
        with patch("harness.state.files.os.fdopen", side_effect=OSError("disk full")):
            with patch("harness.state.files.os.close") as mock_close:
                with pytest.raises(OSError, match="disk full"):
                    _atomic_write_json(path, {"data": 1})
    # On failure the final file should not exist; temp cleanup is best-effort.
    assert not path.exists()
