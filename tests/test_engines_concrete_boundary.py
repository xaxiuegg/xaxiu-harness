"""Boundary tests for src.harness.engines.concrete.

Covers all three HTTP-backed concrete engines with httpx.MockTransport.
No real network calls are made.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from harness.engines.concrete import (
    AnthropicConcrete,
    DeepSeekConcrete,
    KimiConcrete,
)

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
def deepseek_engine(monkeypatch: pytest.MonkeyPatch) -> DeepSeekConcrete:
    monkeypatch.setattr(DeepSeekConcrete, "__abstractmethods__", frozenset())
    cls = _make_testable(DeepSeekConcrete, "deepseek")
    monkeypatch.setattr(DeepSeekConcrete, "__init__", cls.__init__)
    monkeypatch.setattr(DeepSeekConcrete, "name", cls.name)
    return DeepSeekConcrete("ds-key")  # type: ignore[call-arg]


@pytest.fixture
def kimi_engine(monkeypatch: pytest.MonkeyPatch) -> KimiConcrete:
    monkeypatch.setattr(KimiConcrete, "__abstractmethods__", frozenset())
    cls = _make_testable(KimiConcrete, "kimi")
    monkeypatch.setattr(KimiConcrete, "__init__", cls.__init__)
    monkeypatch.setattr(KimiConcrete, "name", cls.name)
    return KimiConcrete("kimi-key")  # type: ignore[call-arg]


@pytest.fixture
def anthropic_engine(monkeypatch: pytest.MonkeyPatch) -> AnthropicConcrete:
    monkeypatch.setattr(AnthropicConcrete, "__abstractmethods__", frozenset())
    cls = _make_testable(AnthropicConcrete, "anthropic")
    monkeypatch.setattr(AnthropicConcrete, "__init__", cls.__init__)
    monkeypatch.setattr(AnthropicConcrete, "name", cls.name)
    return AnthropicConcrete("anthro-key")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# DeepSeekConcrete
# ---------------------------------------------------------------------------

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_JSON_OK = {"choices": [{"message": {"content": "deepseek-ok"}}]}


def test_deepseek_success(
    monkeypatch: pytest.MonkeyPatch, deepseek_engine: DeepSeekConcrete
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=DEEPSEEK_JSON_OK)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = deepseek_engine.dispatch("hello", "deepseek-chat", {})

    assert resp.success is True
    assert resp.text == "deepseek-ok"
    assert resp.error is None
    assert captured["url"] == DEEPSEEK_URL
    assert captured["headers"]["authorization"] == "Bearer ds-key"
    assert captured["headers"]["user-agent"].startswith("xaxiu-harness/")
    assert captured["body"]["model"] == "deepseek-chat"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert "temperature" in captured["body"]


def test_deepseek_401(
    monkeypatch: pytest.MonkeyPatch, deepseek_engine: DeepSeekConcrete
) -> None:
    transport = _mock_transport(status_code=401, json_body={"error": "unauthorized"})
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = deepseek_engine.dispatch("hello", "deepseek-chat", {})

    assert resp.success is False
    assert "401" in resp.error


def test_deepseek_429(
    monkeypatch: pytest.MonkeyPatch, deepseek_engine: DeepSeekConcrete
) -> None:
    transport = _mock_transport(
        status_code=429,
        json_body={"error": "rate_limit"},
        headers={"retry-after": "60"},
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = deepseek_engine.dispatch("hello", "deepseek-chat", {})

    assert resp.success is False
    assert resp.error == "HTTP 429"


def test_deepseek_500(
    monkeypatch: pytest.MonkeyPatch, deepseek_engine: DeepSeekConcrete
) -> None:
    transport = _mock_transport(status_code=500, json_body={"error": "server err"})
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = deepseek_engine.dispatch("hello", "deepseek-chat", {})

    assert resp.success is False
    assert resp.error == "HTTP 500"


def test_deepseek_connect_error(
    monkeypatch: pytest.MonkeyPatch, deepseek_engine: DeepSeekConcrete
) -> None:
    transport = _mock_transport(exc=httpx.ConnectError("Connection refused"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = deepseek_engine.dispatch("hello", "deepseek-chat", {})

    assert resp.success is False
    assert resp.error == "network"


def test_deepseek_timeout(
    monkeypatch: pytest.MonkeyPatch, deepseek_engine: DeepSeekConcrete
) -> None:
    transport = _mock_transport(exc=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = deepseek_engine.dispatch("hello", "deepseek-chat", {})

    assert resp.success is False
    assert resp.error == "timeout"


def test_deepseek_malformed_json(
    monkeypatch: pytest.MonkeyPatch, deepseek_engine: DeepSeekConcrete
) -> None:
    transport = _mock_transport(status_code=200, text_body="not json")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = deepseek_engine.dispatch("hello", "deepseek-chat", {})

    assert resp.success is False
    assert resp.error == "internal"


# ---------------------------------------------------------------------------
# KimiConcrete
# ---------------------------------------------------------------------------

KIMI_URL = "https://api.moonshot.cn/v1/chat/completions"
KIMI_JSON_OK = {"choices": [{"message": {"content": "kimi-ok"}}]}


def test_kimi_success(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=KIMI_JSON_OK)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is True
    assert resp.text == "kimi-ok"
    assert resp.error is None
    assert captured["url"] == KIMI_URL
    assert captured["headers"]["authorization"] == "Bearer kimi-key"
    assert captured["headers"]["user-agent"].startswith("xaxiu-harness/")
    assert captured["body"]["model"] == "kimi-model"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]


def test_kimi_401(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    transport = _mock_transport(status_code=401, json_body={"error": "unauthorized"})
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is False
    assert "401" in resp.error


def test_kimi_429(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    transport = _mock_transport(
        status_code=429,
        json_body={"error": "rate_limit"},
        headers={"retry-after": "30"},
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is False
    assert resp.error == "HTTP 429"


def test_kimi_500(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    transport = _mock_transport(status_code=500, json_body={"error": "server err"})
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is False
    assert resp.error == "HTTP 500"


def test_kimi_connect_error(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    transport = _mock_transport(exc=httpx.ConnectError("Connection refused"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is False
    assert resp.error == "network"


def test_kimi_timeout(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    transport = _mock_transport(exc=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is False
    assert resp.error == "timeout"


def test_kimi_malformed_json(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    transport = _mock_transport(status_code=200, text_body="not json")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is False
    assert resp.error == "internal"


# ---------------------------------------------------------------------------
# AnthropicConcrete
# ---------------------------------------------------------------------------

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_JSON_OK = {"content": [{"type": "text", "text": "anthropic-ok"}]}


def test_anthropic_success(
    monkeypatch: pytest.MonkeyPatch, anthropic_engine: AnthropicConcrete
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ANTHROPIC_JSON_OK)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = anthropic_engine.dispatch("hello", "claude-3", {})

    assert resp.success is True
    assert resp.text == "anthropic-ok"
    assert resp.error is None
    assert captured["url"] == ANTHROPIC_URL
    assert captured["headers"]["x-api-key"] == "anthro-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["headers"]["user-agent"].startswith("xaxiu-harness/")
    assert captured["body"]["model"] == "claude-3"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured["body"]["max_tokens"] == 8192


def test_anthropic_401(
    monkeypatch: pytest.MonkeyPatch, anthropic_engine: AnthropicConcrete
) -> None:
    transport = _mock_transport(status_code=401, json_body={"error": "unauthorized"})
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = anthropic_engine.dispatch("hello", "claude-3", {})

    assert resp.success is False
    assert "401" in resp.error


def test_anthropic_429(
    monkeypatch: pytest.MonkeyPatch, anthropic_engine: AnthropicConcrete
) -> None:
    transport = _mock_transport(
        status_code=429,
        json_body={"error": "rate_limit"},
        headers={"retry-after": "120"},
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = anthropic_engine.dispatch("hello", "claude-3", {})

    assert resp.success is False
    assert resp.error == "HTTP 429"


def test_anthropic_500(
    monkeypatch: pytest.MonkeyPatch, anthropic_engine: AnthropicConcrete
) -> None:
    transport = _mock_transport(status_code=500, json_body={"error": "server err"})
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = anthropic_engine.dispatch("hello", "claude-3", {})

    assert resp.success is False
    assert resp.error == "HTTP 500"


def test_anthropic_connect_error(
    monkeypatch: pytest.MonkeyPatch, anthropic_engine: AnthropicConcrete
) -> None:
    transport = _mock_transport(exc=httpx.ConnectError("Connection refused"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = anthropic_engine.dispatch("hello", "claude-3", {})

    assert resp.success is False
    assert resp.error == "network"


def test_anthropic_timeout(
    monkeypatch: pytest.MonkeyPatch, anthropic_engine: AnthropicConcrete
) -> None:
    transport = _mock_transport(exc=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = anthropic_engine.dispatch("hello", "claude-3", {})

    assert resp.success is False
    assert resp.error == "timeout"


def test_anthropic_malformed_json(
    monkeypatch: pytest.MonkeyPatch, anthropic_engine: AnthropicConcrete
) -> None:
    transport = _mock_transport(status_code=200, text_body="not json")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = anthropic_engine.dispatch("hello", "claude-3", {})

    assert resp.success is False
    assert resp.error == "internal"
