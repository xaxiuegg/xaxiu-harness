"""Tests for harness.proxy.state — schemas and atomic persistence."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.proxy.state import (
    CircuitState,
    KeyState,
    ProxyState,
    read_state,
    write_state,
    _default_state_path,
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


# ---- Edge-case coverage additions ----


def test_key_state_negative_in_flight() -> None:
    with pytest.raises(ValueError):
        KeyState(key_alias="k1", in_flight=-1)


def test_key_state_max_concurrent_zero() -> None:
    with pytest.raises(ValueError):
        KeyState(key_alias="k1", max_concurrent=0)


def test_key_state_invalid_alias() -> None:
    invalid_aliases = [
        "",           # empty
        "1abc",       # starts with digit
        "Abc",        # uppercase
        "a" * 33,     # too long (>32)
        "abc!def",    # invalid char
        "-abc",       # starts with hyphen
        "_abc",       # starts with underscore
    ]
    for alias in invalid_aliases:
        with pytest.raises(ValueError):
            KeyState(key_alias=alias)


def test_key_state_invalid_circuit_state() -> None:
    with pytest.raises(ValueError):
        KeyState(key_alias="k1", circuit_state="unknown_state")


def test_proxy_state_empty_keys_valid() -> None:
    now = datetime.now(timezone.utc).isoformat()
    state = ProxyState(started_at=now, keys={})
    assert len(state.keys) == 0
    assert state.schema_version == 1


def test_read_state_corrupt_json(state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("not valid json{{{")
    with pytest.raises(json.JSONDecodeError):
        read_state(state_file)


def test_proxy_state_complex_roundtrip(state_file: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    original = ProxyState(
        started_at=now,
        keys={
            "k1": KeyState(
                key_alias="k1",
                circuit_state=CircuitState.OPEN,
                in_flight=3,
                max_concurrent=12,
                recent_outcomes=["ok", "fail"],
                consecutive_failures=5,
                cooldown_until=now,
                total_dispatched=100,
                total_failed=10,
                avg_latency_ms=45.5,
                last_used_at=now,
                permanent=True,
            ),
            "k2": KeyState(
                key_alias="k2",
                circuit_state=CircuitState.HALF_OPEN,
                in_flight=0,
                max_concurrent=6,
                recent_outcomes=[],
                consecutive_failures=1,
                cooldown_until=None,
                total_dispatched=50,
                total_failed=2,
                avg_latency_ms=12.0,
                last_used_at=None,
                permanent=False,
            ),
            "k3": KeyState(
                key_alias="k3",
                circuit_state=CircuitState.CLOSED,
            ),
        },
        routing_strategy="round_robin",
        total_requests=200,
        total_errors=15,
    )
    write_state(original, state_file)
    loaded = read_state(state_file)
    assert loaded.started_at == now
    assert set(loaded.keys) == {"k1", "k2", "k3"}
    assert loaded.keys["k1"].circuit_state == CircuitState.OPEN
    assert loaded.keys["k2"].circuit_state == CircuitState.HALF_OPEN
    assert loaded.keys["k3"].circuit_state == CircuitState.CLOSED
    assert loaded.keys["k1"].in_flight == 3
    assert loaded.keys["k1"].max_concurrent == 12
    assert loaded.keys["k1"].recent_outcomes == ["ok", "fail"]
    assert loaded.keys["k1"].consecutive_failures == 5
    assert loaded.keys["k1"].cooldown_until == now
    assert loaded.keys["k1"].total_dispatched == 100
    assert loaded.keys["k1"].total_failed == 10
    assert loaded.keys["k1"].avg_latency_ms == 45.5
    assert loaded.keys["k1"].last_used_at == now
    assert loaded.keys["k1"].permanent is True
    assert loaded.routing_strategy == "round_robin"
    assert loaded.total_requests == 200
    assert loaded.total_errors == 15


def test_recent_outcomes_max_length_rejected() -> None:
    outcomes = ["ok"] * 25
    with pytest.raises(ValueError):
        KeyState(key_alias="k1", recent_outcomes=outcomes)


def test_recent_outcomes_at_max_length_accepted() -> None:
    outcomes = ["ok"] * 20
    ks = KeyState(key_alias="k1", recent_outcomes=outcomes)
    assert len(ks.recent_outcomes) == 20


def test_key_state_cooldown_until_iso8601_and_none() -> None:
    now = datetime.now(timezone.utc).isoformat()
    ks_with_str = KeyState(key_alias="k1", cooldown_until=now)
    assert ks_with_str.cooldown_until == now
    ks_with_none = KeyState(key_alias="k1", cooldown_until=None)
    assert ks_with_none.cooldown_until is None


def test_read_state_default_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    default_path = tmp_path / ".harness" / "proxy_state.json"
    monkeypatch.setattr("harness.proxy.state._default_state_path", lambda: default_path)
    default_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    write_state(ProxyState(started_at=now, keys={}), path=None)
    loaded = read_state(path=None)
    assert loaded.started_at == now


def test_write_state_default_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    default_path = tmp_path / ".harness" / "proxy_state.json"
    monkeypatch.setattr("harness.proxy.state._default_state_path", lambda: default_path)
    now = datetime.now(timezone.utc).isoformat()
    write_state(ProxyState(started_at=now, keys={}), path=None)
    assert default_path.exists()


def test_write_state_cleanup_unlink_fails(state_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc).isoformat()

    def raise_on_replace(_s: str, _d: str) -> None:
        raise OSError("replace failed")

    def raise_on_unlink(_p: str) -> None:
        raise OSError("unlink failed")

    monkeypatch.setattr(os, "replace", raise_on_replace)
    monkeypatch.setattr(os, "unlink", raise_on_unlink)

    with pytest.raises(OSError, match="replace failed"):
        write_state(ProxyState(started_at=now, keys={}), state_file)
