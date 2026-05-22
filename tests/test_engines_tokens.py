"""W4-K: verify token-usage extraction lands in EngineResponse.

Pre-W4-K every ledger row reported tokens_in=0/tokens_out=0 because the
concrete engines never read the `usage` block off the JSON response.
This test pins the wiring for all four backends: DeepSeek/Kimi/MiMo all
use OpenAI-compat `prompt_tokens`+`completion_tokens`; Anthropic uses
`input_tokens`+`output_tokens`.

Pure unit test (no live HTTP) — uses httpx.MockTransport.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from harness.engines.concrete import (
    AnthropicConcrete,
    DeepSeekConcrete,
    KimiConcrete,
    MiMoConcrete,
    _extract_anthropic_usage,
    _extract_openai_usage,
)


_ORIGINAL_HTTPX_CLIENT = httpx.Client


def _swap_httpx(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler)),
    )


# ---------------------------------------------------------------------------
# Helpers — exhaustive coverage of malformed-usage shapes
# ---------------------------------------------------------------------------

def test_extract_openai_usage_full() -> None:
    data = {"usage": {"prompt_tokens": 123, "completion_tokens": 45}}
    assert _extract_openai_usage(data) == (123, 45)


def test_extract_openai_usage_missing_block() -> None:
    assert _extract_openai_usage({}) == (0, 0)


def test_extract_openai_usage_block_not_dict() -> None:
    assert _extract_openai_usage({"usage": "not-a-dict"}) == (0, 0)


def test_extract_openai_usage_non_numeric() -> None:
    data = {"usage": {"prompt_tokens": "many", "completion_tokens": None}}
    assert _extract_openai_usage(data) == (0, 0)


def test_extract_anthropic_usage_full() -> None:
    data = {"usage": {"input_tokens": 234, "output_tokens": 67}}
    assert _extract_anthropic_usage(data) == (234, 67)


def test_extract_anthropic_usage_missing_block() -> None:
    assert _extract_anthropic_usage({}) == (0, 0)


# ---------------------------------------------------------------------------
# End-to-end: tokens propagate from API JSON to EngineResponse
# ---------------------------------------------------------------------------

def _patch_abstract(monkeypatch: pytest.MonkeyPatch, cls: type) -> None:
    monkeypatch.setattr(cls, "__abstractmethods__", frozenset())


def test_deepseek_dispatch_populates_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_abstract(monkeypatch, DeepSeekConcrete)
    body = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 100},
    }
    _swap_httpx(monkeypatch, lambda req: httpx.Response(200, json=body))
    eng = DeepSeekConcrete("ds-key")
    resp = eng.dispatch("hello", "deepseek-chat", {})
    assert resp.success is True
    assert resp.tokens_in == 50
    assert resp.tokens_out == 100


def test_kimi_dispatch_populates_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_abstract(monkeypatch, KimiConcrete)
    body = {
        "choices": [{"message": {"content": "kimi-ok"}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
    }
    _swap_httpx(monkeypatch, lambda req: httpx.Response(200, json=body))
    eng = KimiConcrete("kimi-key")
    resp = eng.dispatch("hi", "kimi-for-coding", {})
    assert resp.success is True
    assert resp.tokens_in == 11
    assert resp.tokens_out == 22


def test_mimo_dispatch_populates_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_abstract(monkeypatch, MiMoConcrete)
    body = {
        "choices": [{"message": {"content": "mimo-ok"}}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 75},
    }
    _swap_httpx(monkeypatch, lambda req: httpx.Response(200, json=body))
    eng = MiMoConcrete("mimo-key")
    resp = eng.dispatch("hi", "mimo-v2.5-pro", {})
    assert resp.success is True
    assert resp.tokens_in == 200
    assert resp.tokens_out == 75


def test_anthropic_dispatch_populates_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_abstract(monkeypatch, AnthropicConcrete)
    body = {
        "content": [{"type": "text", "text": "claude-ok"}],
        "usage": {"input_tokens": 17, "output_tokens": 33},
    }
    _swap_httpx(monkeypatch, lambda req: httpx.Response(200, json=body))
    eng = AnthropicConcrete("ant-key")
    resp = eng.dispatch("hi", "claude-sonnet-4-5", {})
    assert resp.success is True
    assert resp.tokens_in == 17
    assert resp.tokens_out == 33


def test_dispatch_no_usage_block_defaults_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """API that omits `usage` shouldn't crash — just falls back to 0/0."""
    _patch_abstract(monkeypatch, DeepSeekConcrete)
    body = {"choices": [{"message": {"content": "no-usage-block"}}]}
    _swap_httpx(monkeypatch, lambda req: httpx.Response(200, json=body))
    eng = DeepSeekConcrete("ds-key")
    resp = eng.dispatch("hello", "deepseek-chat", {})
    assert resp.success is True
    assert resp.tokens_in == 0
    assert resp.tokens_out == 0
