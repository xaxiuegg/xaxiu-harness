"""Tests for ENGINE-PROBE-QUOTA — quota-header extraction in probe_engine_quota."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from harness.cli_helpers import (
    _PROBEABLE_BACKENDS,
    probe_all_engines_quota,
    probe_engine_quota,
)

_ORIGINAL_HTTPX_CLIENT = httpx.Client


@pytest.fixture(autouse=True)
def _patch_get_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("harness.cli_helpers.get_engine", lambda name: None)


def _quota_transport(headers: dict[str, str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers)
    return httpx.MockTransport(handler)


def test_probe_engine_quota_returns_dict_shape(monkeypatch) -> None:
    """Result always has status + limit/remaining/reset/raw_status_code/error keys."""
    transport = _quota_transport({})
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=transport),
    )
    result = probe_engine_quota("kimi")
    assert set(result.keys()) >= {
        "status", "limit", "remaining", "reset", "raw_status_code", "error",
    }
    assert result["status"] == "up"
    assert result["limit"] is None
    assert result["remaining"] is None


def test_probe_engine_quota_parses_x_ratelimit_headers(monkeypatch) -> None:
    transport = _quota_transport({
        "x-ratelimit-limit": "5000",
        "x-ratelimit-remaining": "4123",
        "x-ratelimit-reset": "2026-05-21T03:00:00Z",
    })
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=transport),
    )
    result = probe_engine_quota("kimi")
    assert result["status"] == "up"
    assert result["limit"] == 5000
    assert result["remaining"] == 4123
    assert result["reset"] == "2026-05-21T03:00:00Z"


def test_probe_engine_quota_handles_alternate_header_spelling(monkeypatch) -> None:
    """Anthropic-style x-ratelimit-*-requests headers are picked up too."""
    transport = _quota_transport({
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "987",
        "x-ratelimit-reset-requests": "60s",
    })
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=transport),
    )
    result = probe_engine_quota("anthropic")
    assert result["limit"] == 1000
    assert result["remaining"] == 987
    assert result["reset"] == "60s"


def test_probe_engine_quota_unknown_engine() -> None:
    result = probe_engine_quota("bogus-engine")
    assert result["status"] == "down"
    assert "Unknown engine" in (result["error"] or "")


def test_probe_engine_quota_handles_network_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=transport),
    )
    result = probe_engine_quota("kimi")
    assert result["status"] == "down"
    assert result["error"] == "network"


def test_probe_engine_quota_non_numeric_limit_falls_back_to_string(monkeypatch) -> None:
    transport = _quota_transport({"x-ratelimit-limit": "unlimited"})
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=transport),
    )
    result = probe_engine_quota("kimi")
    assert result["limit"] == "unlimited"


def test_probe_all_engines_quota_returns_one_entry_per_probeable(monkeypatch) -> None:
    transport = _quota_transport({})
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=transport),
    )
    result = probe_all_engines_quota()
    assert set(result.keys()) == set(_PROBEABLE_BACKENDS)
    for name, info in result.items():
        assert info["status"] == "up"
