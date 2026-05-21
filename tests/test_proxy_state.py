"""Tests for harness.proxy.state — schemas and atomic persistence."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.proxy.state import (
    CircuitState,
    KeyState,
    ProxyState,
    read_state,
    write_state,
)


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "proxy_state.json"
    monkeypatch.setattr(
        "harness.proxy.state._default_state_path",
        lambda: path,
    )
    return path


def test_key_state_defaults() -> None:
    ks = KeyState(key_alias="k1")
    assert ks.circuit_state == CircuitState.CLOSED
    assert ks.max_concurrent == 6
    assert ks.in_flight == 0


def test_proxy_state_roundtrip(state_file: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    original = ProxyState(
        started_at=now,
        keys={"k1": KeyState(key_alias="k1"), "k2": KeyState(key_alias="k2")},
    )
    write_state(original, state_file)
    loaded = read_state(state_file)
    assert loaded.started_at == now
    assert set(loaded.keys) == {"k1", "k2"}


def test_read_state_missing(state_file: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_state(state_file)


def test_write_state_atomic(state_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc).isoformat()
    state = ProxyState(started_at=now, keys={})
    write_state(state, state_file)

    # Corrupt write by making os.replace raise
    monkeypatch.setattr(os, "replace", lambda _s, _d: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        write_state(ProxyState(started_at=now, keys={"k1": KeyState(key_alias="k1")}), state_file)

    # Original file should still be intact
    loaded = read_state(state_file)
    assert loaded.keys == {}


def test_key_state_extra_forbidden() -> None:
    with pytest.raises(ValueError):
        KeyState(key_alias="k1", unknown_field=True)


def test_proxy_state_extra_forbidden() -> None:
    now = datetime.now(timezone.utc).isoformat()
    with pytest.raises(ValueError):
        ProxyState(started_at=now, unknown_field=True)
