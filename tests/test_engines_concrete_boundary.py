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
    GeminiConcrete,
    KimiConcrete,
    _resolve_kimi_upstream,
    get_engine,
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
    """W5-MM: DeepSeek now streams (SSE).  Probe measured 4× total
    latency improvement (10.6s → 2.8s) and 13× TTFB improvement."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        # Return SSE-streaming response (standard OpenAI "data: " format
        # since DeepSeek emits the spec-compliant variant).
        sse = (
            'data: {"choices":[{"delta":{"content":"deepseek-ok"}}]}\n\n'
            'data: {"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

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
    # W5-MM: stream=true is always set for DeepSeek
    assert captured["body"]["stream"] is True


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
    """W5-MM: streaming response with no parseable SSE chunks → error
    `parse_error_no_chunks` (same diagnostic as Kimi's W5-V path)."""
    transport = _mock_transport(status_code=200, text_body="not json")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = deepseek_engine.dispatch("hello", "deepseek-chat", {})

    assert resp.success is False
    assert resp.error == "parse_error_no_chunks"


# ---------------------------------------------------------------------------
# KimiConcrete
# ---------------------------------------------------------------------------

# Default Kimi endpoint updated 2026-05-21 (battle-test finding #7).
# Operator uses Kimi Code (kimi.ai) — `api.moonshot.cn` was a wrong default.
KIMI_URL = "https://api.kimi.com/coding/v1/chat/completions"
KIMI_PROXY_URL = "http://127.0.0.1:7879/v1/chat/completions"
KIMI_JSON_OK = {"choices": [{"message": {"content": "kimi-ok"}}]}


def test_resolve_kimi_upstream_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_PROXY_URL", "http://custom-proxy:9999/v1/chat/completions")
    assert _resolve_kimi_upstream() == "http://custom-proxy:9999/v1/chat/completions"


def test_resolve_kimi_upstream_pid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARNESS_PROXY_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    pid_file = tmp_path / ".harness" / "proxy.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("12345")
    assert _resolve_kimi_upstream() == KIMI_PROXY_URL


def test_resolve_kimi_upstream_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARNESS_PROXY_URL", raising=False)
    assert _resolve_kimi_upstream() == KIMI_URL


def test_kimi_success(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    """W5-V: Kimi streams (data:<json> SSE format, no space after colon)."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        # Return SSE-streaming response (Kimi's non-standard 'data:<json>' format)
        sse = (
            'data:{"choices":[{"delta":{"content":"kimi-ok"}}]}\n\n'
            'data:{"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
            'data:[DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is True
    assert resp.text == "kimi-ok"
    assert resp.error is None
    assert captured["url"] == KIMI_URL
    assert captured["headers"]["authorization"] == "Bearer kimi-key"
    # Kimi Code API enforces a User-Agent allowlist (battle-test #7);
    # default is `claude-code/0.1.0`, configurable via KIMI_USER_AGENT.
    assert captured["headers"]["user-agent"] == "claude-code/0.1.0"
    assert captured["body"]["model"] == "kimi-model"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]
    # W5-V: stream=true is always set for Kimi
    assert captured["body"]["stream"] is True


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
    """W5-V: when stream returns 200 but no parseable chunks, surface as
    parse_error_no_chunks so the fallback chain fires."""
    transport = _mock_transport(status_code=200, text_body="not json")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=transport)
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is False
    assert resp.error == "parse_error_no_chunks"


def test_kimi_routes_through_proxy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kimi_engine: KimiConcrete
) -> None:
    """W5-V: stream proxy variant — same as test_kimi_success but with
    HARNESS_PROXY_URL routing."""
    monkeypatch.setenv("HARNESS_PROXY_URL", "http://proxy-test:7879/v1/chat/completions")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        sse = (
            'data:{"choices":[{"delta":{"content":"kimi-ok"}}]}\n\n'
            'data:{"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
            'data:[DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is True
    assert captured["url"] == "http://proxy-test:7879/v1/chat/completions"


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


# ---------------------------------------------------------------------------
# get_engine factory
# ---------------------------------------------------------------------------


def test_get_engine_returns_gemini_concrete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
    engine = get_engine("gemini", prefer_dpapi=False)
    assert isinstance(engine, GeminiConcrete)


def test_get_engine_gemini_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        get_engine("gemini", prefer_dpapi=False)
    assert "gemini" in str(exc_info.value)


# ---------------------------------------------------------------------------
# WIRE-ENGINE-TIMEOUT (2026-05-22) — read timeout 120→600s
# ---------------------------------------------------------------------------

def test_default_read_timeout_is_at_least_600s() -> None:
    """Bumped from 120 to 600 so DeepSeek V4 Pro (~165s e2e) doesn't time out."""
    from harness.engines.concrete import _DEFAULT_TIMEOUT
    assert _DEFAULT_TIMEOUT.read >= 600


def test_default_read_timeout_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """HARNESS_ENGINE_READ_TIMEOUT_S should be honoured at import time."""
    monkeypatch.setenv("HARNESS_ENGINE_READ_TIMEOUT_S", "30")
    import importlib
    import harness.engines.concrete as mod
    importlib.reload(mod)
    try:
        assert mod._DEFAULT_TIMEOUT.read == 30.0
    finally:
        monkeypatch.delenv("HARNESS_ENGINE_READ_TIMEOUT_S")
        importlib.reload(mod)


# ---------------------------------------------------------------------------
# WIRE-MAX-TOKENS (2026-05-22) — explicit max_tokens on Kimi + DeepSeek
# ---------------------------------------------------------------------------

def test_kimi_payload_includes_max_tokens_default() -> None:
    # W5-W 2026-05-23: operator directive "do not limit max_tokens of
    # Kimi" — default raised from 32K to 200K (Kimi K2.6 supports 256K
    # total context, 200K output leaves a small input budget).
    payload = KimiConcrete._build_payload("hello", "kimi-for-coding", {})
    assert payload["max_tokens"] == 200_000


def test_kimi_payload_max_tokens_overridable() -> None:
    payload = KimiConcrete._build_payload("hello", "kimi-for-coding", {"max_tokens": 8192})
    assert payload["max_tokens"] == 8192


def test_deepseek_payload_includes_max_tokens_default() -> None:
    payload = DeepSeekConcrete._build_payload("hello", "deepseek-v4-flash", {})
    assert payload["max_tokens"] == 32768


def test_deepseek_payload_max_tokens_overridable() -> None:
    payload = DeepSeekConcrete._build_payload("hello", "deepseek-v4-flash", {"max_tokens": 65536})
    assert payload["max_tokens"] == 65536


# ---------------------------------------------------------------------------
# WIRE-MIMO (2026-05-22) — Xiaomi MiMo Open Platform engine
# ---------------------------------------------------------------------------

@pytest.fixture
def mimo_engine(monkeypatch: pytest.MonkeyPatch):
    from harness.engines.concrete import MiMoConcrete
    monkeypatch.setattr(MiMoConcrete, "__abstractmethods__", frozenset())
    cls = _make_testable(MiMoConcrete, "mimo")
    monkeypatch.setattr(MiMoConcrete, "__init__", cls.__init__)
    monkeypatch.setattr(MiMoConcrete, "name", cls.name)
    return MiMoConcrete("sk-test")  # type: ignore[call-arg]


def test_resolve_mimo_upstream_tp_key_goes_to_tokenplan(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.engines.concrete import _resolve_mimo_upstream
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    monkeypatch.delenv("MIMO_REGION", raising=False)
    # WIRE-MIMO-SGP (2026-05-22): default international region is Singapore.
    # Operator's actual tp- key is provisioned against the SGP gateway —
    # ams + cn return 401 invalid_key for it.
    assert _resolve_mimo_upstream("tp-abc123") == \
        "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"


def test_resolve_mimo_upstream_sk_key_goes_to_payg(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.engines.concrete import _resolve_mimo_upstream
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    assert _resolve_mimo_upstream("sk-abc123") == \
        "https://api.xiaomimimo.com/v1/chat/completions"


def test_resolve_mimo_upstream_explicit_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.engines.concrete import _resolve_mimo_upstream
    monkeypatch.setenv("MIMO_BASE_URL", "https://my-proxy.local/v1")
    assert _resolve_mimo_upstream("tp-abc") == \
        "https://my-proxy.local/v1/chat/completions"
    monkeypatch.setenv("MIMO_BASE_URL", "https://my-proxy.local/v1/chat/completions")
    assert _resolve_mimo_upstream("sk-abc") == \
        "https://my-proxy.local/v1/chat/completions"


def test_mimo_payload_shape() -> None:
    # W5-W 2026-05-23: operator directive "do not limit max_tokens of
    # unlimited-subscription engines" — MiMo default raised from 32K to
    # 131K (hardware max).
    from harness.engines.concrete import MiMoConcrete
    p = MiMoConcrete._build_payload("hi", "mimo-v2.5-pro", {})
    assert p["model"] == "mimo-v2.5-pro"
    assert p["messages"][0]["content"] == "hi"
    assert p["max_tokens"] == 131_072
    assert "temperature" in p
    assert "thinking" not in p  # only included when explicitly requested


def test_mimo_payload_passes_thinking_when_requested() -> None:
    from harness.engines.concrete import MiMoConcrete
    p = MiMoConcrete._build_payload("hi", "mimo-v2.5-pro", {"thinking": True})
    assert p["thinking"] is True


def test_mimo_dispatch_success(monkeypatch: pytest.MonkeyPatch, mimo_engine) -> None:
    """Mocked happy-path call hits the right URL and returns text."""
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    transport = _mock_transport(
        json_body={"choices": [{"message": {"content": "ok"}}]},
    )
    original = httpx.Client
    captured = {}

    def _capture_client(**kwargs):
        client = original(transport=transport, **kwargs)
        original_post = client.post

        def _post(url, **post_kwargs):
            captured["url"] = url
            captured["headers"] = post_kwargs.get("headers", {})
            captured["json"] = post_kwargs.get("json", {})
            return original_post(url, **post_kwargs)

        client.post = _post  # type: ignore[method-assign]
        return client

    monkeypatch.setattr("harness.engines.concrete.httpx.Client", _capture_client)
    result = mimo_engine.dispatch("hello", "mimo-v2.5", {})
    assert result.success is True
    assert result.text == "ok"
    assert "xiaomimimo.com" in captured["url"]
    assert captured["headers"]["Authorization"].startswith("Bearer ")


def test_get_engine_returns_mimo_concrete(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.engines.concrete import MiMoConcrete
    monkeypatch.setenv("MIMO_API_KEY", "tp-test-key")
    engine = get_engine("mimo", prefer_dpapi=False)
    assert isinstance(engine, MiMoConcrete)


def test_get_engine_mimo_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        get_engine("mimo", prefer_dpapi=False)
    assert "mimo" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Budget integration: MiMo subscription pricing
# ---------------------------------------------------------------------------

def test_budget_normalize_mimo_subscription_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """tp- key → -sub pricing row (free); sk- key → standard pricing."""
    from harness.budget import _normalize_engine
    monkeypatch.setenv("MIMO_API_KEY", "tp-abc")
    assert _normalize_engine("mimo") == "mimo-sub"
    assert _normalize_engine("mimo-v2.5") == "mimo-sub"
    assert _normalize_engine("mimo-pro") == "mimo-pro-sub"
    assert _normalize_engine("swarm/mimo-v2.5-pro") == "mimo-pro-sub"


def test_budget_normalize_mimo_payg_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.budget import _normalize_engine
    monkeypatch.setenv("MIMO_API_KEY", "sk-abc")
    assert _normalize_engine("mimo") == "mimo"
    assert _normalize_engine("swarm/mimo-v2.5") == "mimo"
    assert _normalize_engine("mimo-pro") == "mimo-pro"


def test_budget_mimo_subscription_dispatch_is_zero_cost(tmp_path, monkeypatch) -> None:
    """A tp- key dispatch records cost=0 in the ledger."""
    from harness.budget import record_dispatch
    monkeypatch.setenv("MIMO_API_KEY", "tp-xyz")
    ledger = tmp_path / "ledger.jsonl"
    entry = record_dispatch(
        task_id="t1",
        engine="swarm/mimo-v2.5-pro",
        input_tokens=1_000_000,
        output_tokens=500_000,
        ledger_path=ledger,
    )
    assert entry.cost_usd == 0.0


def test_budget_mimo_payg_dispatch_uses_priced_row(tmp_path, monkeypatch) -> None:
    from harness.budget import record_dispatch
    monkeypatch.setenv("MIMO_API_KEY", "sk-xyz")
    ledger = tmp_path / "ledger.jsonl"
    entry = record_dispatch(
        task_id="t1",
        engine="mimo-v2.5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        ledger_path=ledger,
    )
    # mimo (≤256K cache-miss): input 0.40 + output 2.00 = 2.40 per 1M
    assert entry.cost_usd == round(0.40 + 2.00, 6)


def test_budget_mimo_pro_payg_dispatch_uses_priced_row(tmp_path, monkeypatch) -> None:
    from harness.budget import record_dispatch
    monkeypatch.setenv("MIMO_API_KEY", "sk-xyz")
    ledger = tmp_path / "ledger.jsonl"
    entry = record_dispatch(
        task_id="t1",
        engine="mimo-v2.5-pro",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        ledger_path=ledger,
    )
    # mimo-pro (≤256K cache-miss): input 1.00 + output 3.00 = 4.00 per 1M
    assert entry.cost_usd == round(1.00 + 3.00, 6)


def test_mimo_user_agent_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.engines.concrete import _make_mimo_user_agent
    monkeypatch.delenv("MIMO_USER_AGENT", raising=False)
    assert _make_mimo_user_agent() == "claude-code/0.1.0"
    monkeypatch.setenv("MIMO_USER_AGENT", "OpenCode/1.2")
    assert _make_mimo_user_agent() == "OpenCode/1.2"


def test_resolve_mimo_upstream_defaults_to_singapore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per operator's actual dashboard 2026-05-22: international keys are SGP-bound."""
    from harness.engines.concrete import _resolve_mimo_upstream
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    monkeypatch.delenv("MIMO_REGION", raising=False)
    assert _resolve_mimo_upstream("tp-abc") == \
        "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"


def test_resolve_mimo_upstream_region_cn(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.engines.concrete import _resolve_mimo_upstream
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    monkeypatch.setenv("MIMO_REGION", "cn")
    assert _resolve_mimo_upstream("tp-abc") == \
        "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"


def test_resolve_mimo_upstream_region_ams(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.engines.concrete import _resolve_mimo_upstream
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    monkeypatch.setenv("MIMO_REGION", "ams")
    assert _resolve_mimo_upstream("tp-abc") == \
        "https://token-plan-ams.xiaomimimo.com/v1/chat/completions"


# ---------------------------------------------------------------------------
# WIRE-MIMO-AUTO-ROUTING (2026-05-22) — Pro default, Standard for multimodal
# ---------------------------------------------------------------------------

def test_detect_mimo_model_defaults_to_pro_for_text_only() -> None:
    from harness.engines.concrete import detect_mimo_model, DEFAULT_MIMO_MODEL
    assert DEFAULT_MIMO_MODEL == "mimo-v2.5-pro"
    assert detect_mimo_model("plain text packet content") == "mimo-v2.5-pro"


def test_detect_mimo_model_switches_to_standard_on_markdown_image() -> None:
    from harness.engines.concrete import detect_mimo_model
    packet = "Review this screenshot:\n\n![dashboard](./shots/main.png)\n\nWhat's wrong?"
    assert detect_mimo_model(packet) == "mimo-v2.5"


def test_detect_mimo_model_switches_to_standard_on_html_img_tag() -> None:
    from harness.engines.concrete import detect_mimo_model
    packet = 'Analyze: <img src="diagram.png" alt="flow">'
    assert detect_mimo_model(packet) == "mimo-v2.5"


def test_detect_mimo_model_switches_on_video_tag() -> None:
    from harness.engines.concrete import detect_mimo_model
    assert detect_mimo_model("watch <video src=clip.mp4></video>") == "mimo-v2.5"


def test_detect_mimo_model_switches_on_data_url_image() -> None:
    from harness.engines.concrete import detect_mimo_model
    packet = "Decode: data:image/png;base64,iVBORw0K..."
    assert detect_mimo_model(packet) == "mimo-v2.5"


def test_detect_mimo_model_switches_on_inline_image_extension() -> None:
    from harness.engines.concrete import detect_mimo_model
    packet = "Compare frame1.jpg vs frame2.webp side by side"
    assert detect_mimo_model(packet) == "mimo-v2.5"


def test_detect_mimo_model_explicit_override_wins() -> None:
    from harness.engines.concrete import detect_mimo_model
    # Multimodal content but operator explicitly forces Pro → Pro wins
    assert detect_mimo_model("![x](y.png)", {"model": "mimo-v2.5-pro"}) == "mimo-v2.5-pro"
    # Plain text but operator forces Standard → Standard wins
    assert detect_mimo_model("plain", {"model": "mimo-v2.5"}) == "mimo-v2.5"


def test_detect_mimo_model_extension_is_word_boundary_aware() -> None:
    """A bare word ending in 'png' (e.g. 'png-encoding') should NOT trigger."""
    from harness.engines.concrete import detect_mimo_model
    # Real extension → triggers
    assert detect_mimo_model("see file.png in the repo") == "mimo-v2.5"
    # Text "PNG" without a leading dot or filename context → does NOT trigger
    assert detect_mimo_model("discuss the PNG-encoding scheme") == "mimo-v2.5-pro"


def test_mimo_dispatch_uses_auto_detection_when_model_is_blank(monkeypatch: pytest.MonkeyPatch, mimo_engine) -> None:
    """When dispatch is called with model='' it auto-picks via detect_mimo_model."""
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    captured: dict = {}

    def _capture_client(**kwargs):
        original = _ORIGINAL_HTTPX_CLIENT
        transport = _mock_transport(
            json_body={"choices": [{"message": {"content": "ok"}}]},
        )
        client = original(transport=transport, **kwargs)
        original_post = client.post

        def _post(url, **post_kwargs):
            captured["json"] = post_kwargs.get("json", {})
            return original_post(url, **post_kwargs)

        client.post = _post  # type: ignore[method-assign]
        return client

    monkeypatch.setattr("harness.engines.concrete.httpx.Client", _capture_client)
    # Multimodal packet, empty model → MiMo Standard selected
    mimo_engine.dispatch("![img](x.png)", "", {})
    assert captured["json"]["model"] == "mimo-v2.5"
    captured.clear()
    # Plain text packet, model=auto → MiMo Pro
    mimo_engine.dispatch("hello world", "auto", {})
    assert captured["json"]["model"] == "mimo-v2.5-pro"
    captured.clear()
    # Explicit model string passes through untouched
    mimo_engine.dispatch("![img](x.png)", "mimo-v2.5-pro", {})
    assert captured["json"]["model"] == "mimo-v2.5-pro"


# ---------------------------------------------------------------------------
# WIRE-DEEPSEEK-THINKING (2026-05-22) — preferred config = v4-flash thinking ON
# ---------------------------------------------------------------------------

def test_deepseek_payload_default_no_thinking_field() -> None:
    """DeepSeek API does NOT accept a `thinking` JSON field.  Sending one
    caused HTTP 400 in the 2026-05-22 benchmark.  Default behaviour now
    omits the field entirely so thinking-ON is implicit (operator preference)."""
    p = DeepSeekConcrete._build_payload("hi", "deepseek-v4-flash", {})
    assert "thinking" not in p
    # temperature stays at the thinking-ON default (0.6)
    assert p["temperature"] == 0.6


def test_deepseek_payload_flash_no_longer_auto_disables_thinking() -> None:
    """Regression sentinel: previously model.endswith('-flash') forced
    no_thinking=True, which set the thinking JSON field and broke
    DeepSeek's API.  That auto-coupling is gone."""
    p = DeepSeekConcrete._build_payload("hi", "deepseek-v4-flash", {})
    assert "thinking" not in p
    assert p["temperature"] == 0.6  # NOT 0.0 — thinking is on


def test_deepseek_payload_explicit_no_thinking_lowers_temperature() -> None:
    p = DeepSeekConcrete._build_payload("hi", "deepseek-v4-flash",
                                        {"no_thinking": True})
    assert "thinking" not in p  # still no JSON field — would 400 the API
    assert p["temperature"] == 0.0  # deterministic for surgical patches


def test_deepseek_payload_alternate_no_thinking_alias() -> None:
    """``--no-thinking`` (swarm CLI alias) is also honoured for backward compat."""
    p = DeepSeekConcrete._build_payload("hi", "deepseek-v4-flash",
                                        {"--no-thinking": True})
    assert p["temperature"] == 0.0


# ---------------------------------------------------------------------------
# W7-KIMI-REASONING-EMPTY: reasoning_only flag
# W7-KIMI-MAX-TOKENS-FLOOR: clamp small caller overrides up
# ---------------------------------------------------------------------------


def test_kimi_reasoning_only_set_when_content_empty_but_reasoning_present(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    """W7-KIMI-REASONING-EMPTY 2026-05-23: when Kimi exhausts max_tokens
    on reasoning_content and emits ZERO user-facing content, the
    EngineResponse must set reasoning_only=True so the caller can
    retry with a larger budget instead of relaying empty text."""
    def handler(request: httpx.Request) -> httpx.Response:
        # Stream: reasoning_content only (no content), plus usage block
        sse = (
            'data:{"choices":[{"delta":{"reasoning_content":"thinking..."}}]}\n\n'
            'data:{"choices":[{"delta":{"reasoning_content":" more"}}]}\n\n'
            'data:{"choices":[{"finish_reason":"length"}],"usage":'
            '{"prompt_tokens":100,"completion_tokens":2500}}\n\n'
            'data:[DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(handler)),
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})

    assert resp.success is True, (
        "API call succeeded (200) — the response is a parseable "
        "reasoning-only stream"
    )
    assert resp.text == "", "no user-facing content was emitted"
    assert resp.reasoning_only is True, (
        "reasoning_only must be True when content_chunks=[] but "
        "reasoning_chunks > 0 — this is the W6-PANEL footgun signal"
    )


def test_kimi_reasoning_only_false_when_content_present(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    """Normal happy path: content emitted → reasoning_only=False even
    if reasoning_content also appeared earlier in the stream."""
    def handler(request: httpx.Request) -> httpx.Response:
        sse = (
            'data:{"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n'
            'data:{"choices":[{"delta":{"content":"answer"}}]}\n\n'
            'data:{"choices":[{"finish_reason":"stop"}],"usage":'
            '{"prompt_tokens":10,"completion_tokens":5}}\n\n'
            'data:[DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(handler)),
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})
    assert resp.success is True
    assert resp.text == "answer"
    assert resp.reasoning_only is False


def test_kimi_reasoning_only_false_when_nothing_at_all_parsed(
    monkeypatch: pytest.MonkeyPatch, kimi_engine: KimiConcrete
) -> None:
    """Edge: parse_error_no_chunks (success=False) returns the default
    reasoning_only=False — it's success=True with empty content that
    indicates reasoning-exhausted, not total parse failure."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")  # empty body

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(handler)),
    )

    resp = kimi_engine.dispatch("hello", "kimi-model", {})
    assert resp.success is False
    assert resp.error == "parse_error_no_chunks"
    assert resp.reasoning_only is False


def test_kimi_payload_max_tokens_floor_clamps_low_caller_values() -> None:
    """W7-KIMI-MAX-TOKENS-FLOOR 2026-05-23: when the caller passes a
    max_tokens below the 8K safety floor, the payload clamps UP to 8K
    so reasoning_content can't exhaust the entire budget before any
    content emits.  The W6-PANEL retry hit max_tokens=4000 and
    max_tokens=2500 — both must be bumped."""
    for low in (100, 1000, 2500, 4000, 7999):
        p = KimiConcrete._build_payload("hi", "kimi-model",
                                        {"max_tokens": low})
        assert p["max_tokens"] == 8_000, (
            f"max_tokens={low} should clamp to 8000; got {p['max_tokens']}"
        )


def test_kimi_payload_max_tokens_respects_caller_when_at_or_above_floor() -> None:
    """At-or-above-floor caller values pass through unchanged."""
    for ok in (8_000, 10_000, 16_000, 100_000, 200_000, 256_000):
        p = KimiConcrete._build_payload("hi", "kimi-model",
                                        {"max_tokens": ok})
        assert p["max_tokens"] == ok, (
            f"max_tokens={ok} should pass through unchanged; got {p['max_tokens']}"
        )


def test_kimi_payload_max_tokens_floor_override_escape_hatch() -> None:
    """Callers who genuinely need a small cap can opt-out via the
    `max_tokens_override_floor=True` flag.  The floor still defaults
    to applying to protect naive callers."""
    p = KimiConcrete._build_payload("hi", "kimi-model", {
        "max_tokens": 1_000,
        "max_tokens_override_floor": True,
    })
    assert p["max_tokens"] == 1_000, (
        "explicit floor-override should respect the small cap"
    )


def test_kimi_payload_max_tokens_default_unchanged() -> None:
    """Caller-omitted max_tokens still defaults to 200K (W5-W).  The
    floor logic only applies when the caller passes a value."""
    p = KimiConcrete._build_payload("hi", "kimi-model", {})
    assert p["max_tokens"] == 200_000
