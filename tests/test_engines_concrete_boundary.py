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
    # Kimi Code API enforces a User-Agent allowlist (battle-test #7);
    # default is `claude-code/0.1.0`, configurable via KIMI_USER_AGENT.
    assert captured["headers"]["user-agent"] == "claude-code/0.1.0"
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


def test_kimi_routes_through_proxy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kimi_engine: KimiConcrete
) -> None:
    monkeypatch.setenv("HARNESS_PROXY_URL", "http://proxy-test:7879/v1/chat/completions")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=KIMI_JSON_OK)

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
    payload = KimiConcrete._build_payload("hello", "kimi-for-coding", {})
    assert payload["max_tokens"] == 32768


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
    # Default region is Amsterdam (international); cn requires explicit override
    assert _resolve_mimo_upstream("tp-abc123") == \
        "https://token-plan-ams.xiaomimimo.com/v1/chat/completions"


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
    from harness.engines.concrete import MiMoConcrete
    p = MiMoConcrete._build_payload("hi", "mimo-v2.5-pro", {})
    assert p["model"] == "mimo-v2.5-pro"
    assert p["messages"][0]["content"] == "hi"
    assert p["max_tokens"] == 32768
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


def test_resolve_mimo_upstream_defaults_to_amsterdam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per Xiaomi research 2026-05-22: international users go to Amsterdam by default."""
    from harness.engines.concrete import _resolve_mimo_upstream
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    monkeypatch.delenv("MIMO_REGION", raising=False)
    assert _resolve_mimo_upstream("tp-abc") == \
        "https://token-plan-ams.xiaomimimo.com/v1/chat/completions"


def test_resolve_mimo_upstream_region_cn(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.engines.concrete import _resolve_mimo_upstream
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    monkeypatch.setenv("MIMO_REGION", "cn")
    assert _resolve_mimo_upstream("tp-abc") == \
        "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
