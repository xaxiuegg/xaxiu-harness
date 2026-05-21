"""Boundary tests for src.harness.cli_helpers.

Covers probe_engine and probe_all_engines with httpx.MockTransport.
No real network calls are made.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from harness.cli_helpers import (
    _ENGINE_URLS,
    _PROBEABLE_BACKENDS,
    probe_all_engines,
    probe_engine,
)
from harness._constants import SUPPORTED_BACKENDS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_transport(
    response: httpx.Response | None = None,
    exc: Exception | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        return response or httpx.Response(200)

    return httpx.MockTransport(handler)


def _conditional_transport(
    failing: set[str] | None = None,
    exc: Exception | None = None,
) -> httpx.MockTransport:
    """Return a transport that raises *exc* for URLs belonging to *failing* engines."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for name in failing or []:
            if _ENGINE_URLS.get(name, "") in url:
                raise exc or httpx.ConnectError("fail")
        return httpx.Response(200)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_get_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure get_engine never raises RuntimeError due to missing API keys."""
    monkeypatch.setattr(
        "harness.cli_helpers.get_engine",
        lambda name: None,
    )


# ---------------------------------------------------------------------------
# probe_engine — happy path + error paths
# ---------------------------------------------------------------------------

def test_probe_engine_success(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _mock_transport()
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    status, error = probe_engine("kimi")
    assert status == "up"
    assert error is None


def test_probe_engine_get_engine_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "harness.cli_helpers.get_engine",
        lambda name: (_ for _ in ()).throw(RuntimeError("missing key")),
    )
    status, error = probe_engine("kimi")
    assert status == "down"
    assert "missing key" in error


def test_probe_engine_unknown_engine() -> None:
    status, error = probe_engine("unknown-engine")
    assert status == "down"
    assert "Unknown engine" in error


def test_probe_engine_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _mock_transport(exc=httpx.ConnectError("Connection refused"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    status, error = probe_engine("deepseek")
    assert status == "down"
    assert error == "network"


def test_probe_engine_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _mock_transport(exc=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    status, error = probe_engine("anthropic")
    assert status == "down"
    assert error == "timeout"


def test_probe_engine_generic_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _mock_transport(exc=ValueError("boom"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    status, error = probe_engine("kimi")
    assert status == "down"
    assert "boom" in error


# ---------------------------------------------------------------------------
# probe_all_engines — success, partial failure, all fail, timeout, latency
# ---------------------------------------------------------------------------

def test_probe_all_engines_success(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _mock_transport()
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    result = probe_all_engines()
    assert set(result.keys()) == set(_PROBEABLE_BACKENDS)
    for status, error in result.values():
        assert status == "up"
        assert error is None


def test_probe_all_engines_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _conditional_transport(
        failing={"deepseek"},
        exc=httpx.ConnectError("refused"),
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    result = probe_all_engines()
    assert result["deepseek"] == ("down", "network")
    for name in ("kimi", "anthropic"):
        assert result[name] == ("up", None)


def test_probe_all_engines_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _conditional_transport(
        failing=set(_PROBEABLE_BACKENDS),
        exc=httpx.ConnectError("refused"),
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    result = probe_all_engines()
    for status, error in result.values():
        assert status == "down"
        assert error == "network"


def test_probe_all_engines_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _conditional_transport(
        failing={"kimi"},
        exc=httpx.TimeoutException("timed out"),
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    result = probe_all_engines()
    assert result["kimi"] == ("down", "timeout")
    for name in ("deepseek", "anthropic"):
        assert result[name] == ("up", None)


def test_probe_all_engines_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that probe_all_engines completes within a reasonable wall-clock bound.

    We inject a small per-request delay and assert the total elapsed time is
    at least N * delay, confirming the probes execute sequentially and the
    caller can observe latency.
    """
    delay = 0.01

    def slow_handler(request: httpx.Request) -> httpx.Response:
        time.sleep(delay)
        return httpx.Response(200)

    transport = httpx.MockTransport(slow_handler)
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    t0 = time.monotonic()
    result = probe_all_engines()
    t1 = time.monotonic()

    assert len(result) == len(_PROBEABLE_BACKENDS)
    elapsed = t1 - t0
    assert elapsed >= delay * len(_PROBEABLE_BACKENDS)
