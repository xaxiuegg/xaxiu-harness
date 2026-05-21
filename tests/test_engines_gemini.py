"""Boundary tests for src.harness.engines.gemini.

Covers the Gemini concrete engine with httpx.MockTransport.
No real network calls are made.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from harness.engines.gemini import GeminiConcrete

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _mock_transport(
    status_code: int = 200,
    json_body: dict | None = None,
    text_body: str | None = None,
    headers: dict | None = None,
    exc: Exception | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        if text_body is not None:
            return httpx.Response(
                status_code, text=text_body, headers=headers
            )
        return httpx.Response(
            status_code, json=json_body or {}, headers=headers
        )

    return httpx.MockTransport(handler)


def _make_testable(engine_cls: type, name: str) -> type:
    """Return a testable subclass with __init__ and name property wired."""

    class Testable(engine_cls):
        def __init__(self, api_key: str) -> None:
            self._api_key = api_key

        @property
        def name(self) -> str:
            return name

    return Testable


@pytest.fixture
def gemini_engine(monkeypatch: pytest.MonkeyPatch) -> GeminiConcrete:
    monkeypatch.setattr(GeminiConcrete, "__abstractmethods__", frozenset())
    cls = _make_testable(GeminiConcrete, "gemini")
    monkeypatch.setattr(GeminiConcrete, "__init__", cls.__init__)
    monkeypatch.setattr(GeminiConcrete, "name", cls.name)
    return GeminiConcrete("gemini-key")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# GeminiConcrete
# ---------------------------------------------------------------------------

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-model:generateContent"
GEMINI_JSON_OK = {
    "candidates": [
        {"content": {"parts": [{"text": "gemini-ok"}]}}
    ]
}


def test_gemini_success(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=GEMINI_JSON_OK)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is True
    assert resp.text == "gemini-ok"
    assert resp.error is None
    assert captured["url"].startswith(GEMINI_URL)
    assert "key=gemini-key" in captured["url"]
    assert captured["headers"]["user-agent"].startswith("xaxiu-harness/")
    assert captured["body"]["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert captured["body"]["generationConfig"]["temperature"] == 0.2
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 8192


def test_gemini_success_multiple_parts(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    json_body = {
        "candidates": [
            {"content": {"parts": [{"text": "part1"}, {"text": "part2"}]}}
        ]
    }

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=_mock_transport(json_body=json_body))
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is True
    assert resp.text == "part1part2"


def test_gemini_empty_candidates(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=_mock_transport(json_body={"candidates": []}))
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is False
    assert resp.error == "no_candidates"


def test_gemini_401(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    transport = _mock_transport(status_code=401, json_body={"error": "unauthorized"})
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is False
    assert "401" in resp.error


def test_gemini_429(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    transport = _mock_transport(
        status_code=429,
        json_body={"error": "rate_limit"},
        headers={"retry-after": "60"},
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is False
    assert resp.error == "HTTP 429"


def test_gemini_500(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    transport = _mock_transport(status_code=500, json_body={"error": "server err"})
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is False
    assert resp.error == "HTTP 500"


def test_gemini_connect_error(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    transport = _mock_transport(exc=httpx.ConnectError("Connection refused"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is False
    assert resp.error == "network"


def test_gemini_timeout(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    transport = _mock_transport(exc=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is False
    assert resp.error == "timeout"


def test_gemini_malformed_json(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    transport = _mock_transport(status_code=200, text_body="not json")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {})

    assert resp.success is False
    assert resp.error == "internal"


def test_gemini_missing_api_key(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GeminiConcrete, "__abstractmethods__", frozenset())
    cls = _make_testable(GeminiConcrete, "gemini")
    monkeypatch.setattr(GeminiConcrete, "__init__", cls.__init__)
    monkeypatch.setattr(GeminiConcrete, "name", cls.name)
    engine = GeminiConcrete("")  # type: ignore[call-arg]

    resp = engine.dispatch("hello", "gemini-model", {})

    assert resp.success is False
    assert resp.error == "missing_api_key"


def test_gemini_default_model(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=GEMINI_JSON_OK)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = gemini_engine.dispatch("hello", "", {})

    assert resp.success is True
    assert "gemini-2.0-flash" in captured["url"]


def test_gemini_extra_args_temperature(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=GEMINI_JSON_OK)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {"temperature": 0.7})

    assert resp.success is True
    assert captured["body"]["generationConfig"]["temperature"] == 0.7


def test_gemini_extra_args_max_output_tokens(
    monkeypatch: pytest.MonkeyPatch, gemini_engine: GeminiConcrete
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=GEMINI_JSON_OK)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = gemini_engine.dispatch("hello", "gemini-model", {"max_output_tokens": 4096})

    assert resp.success is True
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 4096
