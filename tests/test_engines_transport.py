"""Tests for harness.engines.transport — StreamingTransport ABC.

The base class is exercised indirectly via DeepSeek/Kimi tests in
test_engines_concrete_boundary.py + test_concrete_mutation_killers.py.
This file adds *direct* tests on the ABC's hooks + dispatch loop so
future engine additions (subclasses) can rely on the documented
contract without grepping the concrete subclasses.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
import pytest

from harness.engines.base import EngineResponse
from harness.engines.transport import StreamingTransport


_ORIGINAL_HTTPX_CLIENT = httpx.Client


class _MinimalTransport(StreamingTransport):
    """Bare-minimum concrete subclass exercising the default hooks."""

    name = "test"

    def __init__(self) -> None:
        self._api_key = "test-key"

    def _endpoint_url(self) -> str:
        return "https://api.example.com/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test-key"}

    def _build_payload(
        self, content: str, model: str, extra: dict[str, Any],
    ) -> dict:
        return {"model": model, "messages": [{"role": "user", "content": content}]}


def _patch_httpx(monkeypatch, handler):
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kwargs: _ORIGINAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(handler)
        ),
    )


def test_default_dispatch_aggregates_content_chunks(monkeypatch) -> None:
    """Standard happy path: 2 content chunks aggregate to one text."""
    def handler(request):
        sse = (
            'data: {"choices":[{"delta":{"content":"foo"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"bar"}}]}\n\n'
            'data: {"choices":[{"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is True
    assert resp.text == "foobar"
    assert resp.tokens_in == 3
    assert resp.tokens_out == 2


def test_default_dispatch_handles_both_sse_prefixes(monkeypatch) -> None:
    """SSE prefix variants — standard ``data: `` AND no-space ``data:``
    (W5-V wiring fix applied universally via base class)."""
    def handler(request):
        sse = (
            'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
            'data:{"choices":[{"delta":{"content":"B"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is True
    assert resp.text == "AB"


def test_default_dispatch_returns_parse_error_on_empty_stream(
    monkeypatch
) -> None:
    """No chunks, no usage, no finish_reason → parse_error_no_chunks."""
    def handler(request):
        return httpx.Response(200, content=b"")

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is False
    assert resp.error == "parse_error_no_chunks"


def test_default_dispatch_returns_http_error_for_non_200(monkeypatch) -> None:
    def handler(request):
        return httpx.Response(500, json={"error": "server down"})

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is False
    assert resp.error.startswith("HTTP 500")


def test_default_dispatch_handles_timeout(monkeypatch) -> None:
    """W13-ENGINE-RETRY-RESILIENT 2026-05-25: timeout is now retried
    ONCE before returning failure.  We raise the same exception both
    attempts to force the failure path."""
    def handler(request):
        raise httpx.TimeoutException("server too slow")

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is False
    assert resp.error.startswith("timeout"), resp.error


def test_default_dispatch_handles_connect_error(monkeypatch) -> None:
    def handler(request):
        raise httpx.ConnectError("dns fail")

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is False
    # W13: error preserves repr(exc), prefixed with "network: "
    assert resp.error.startswith("network"), resp.error


def test_default_dispatch_handles_remote_protocol_error_default(
    monkeypatch
) -> None:
    """W13-ENGINE-RETRY-RESILIENT 2026-05-25: default
    ``_handle_remote_protocol_error`` returns None → first attempt
    re-raises → run_with_retry retries once → if the second attempt
    also raises RemoteProtocolError, the failure response carries
    the categorized error with 'remote_protocol_error' prefix."""
    def handler(request):
        raise httpx.RemoteProtocolError("disconnected")

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is False
    assert resp.error.startswith("remote_protocol_error"), resp.error


def test_subclass_remote_protocol_error_hook_rescues_partial(
    monkeypatch
) -> None:
    """A subclass that overrides ``_handle_remote_protocol_error``
    (like KimiConcrete) can return a partial-success EngineResponse."""

    class _Rescuer(_MinimalTransport):
        def _handle_remote_protocol_error(self, accumulated, latency_ms):
            return EngineResponse(
                success=True, text="rescued-partial",
                latency_ms=latency_ms, error=None,
            )

    def handler(request):
        raise httpx.RemoteProtocolError("disconnected")

    _patch_httpx(monkeypatch, handler)
    eng = _Rescuer()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is True
    assert resp.text == "rescued-partial"


def test_subclass_process_delta_hook_captures_custom_fields(
    monkeypatch
) -> None:
    """A subclass that overrides ``_process_delta`` (like KimiConcrete)
    captures fields beyond ``content``."""

    class _ReasoningCapture(_MinimalTransport):
        def _process_delta(self, delta, accumulated):
            super()._process_delta(delta, accumulated)
            if delta.get("reasoning_content"):
                accumulated.setdefault(
                    "reasoning_chunks", []
                ).append(delta["reasoning_content"])

        def _finalize_response(
            self, accumulated, latency_ms, usage_info, finish_reason,
        ):
            base = super()._finalize_response(
                accumulated, latency_ms, usage_info, finish_reason,
            )
            # Surface reasoning via the response's text (test-only signal)
            reasoning = "".join(accumulated.get("reasoning_chunks", []))
            return EngineResponse(
                success=base.success,
                text=f"{base.text}|reasoning={reasoning}",
                latency_ms=base.latency_ms,
                error=base.error,
                tokens_in=base.tokens_in, tokens_out=base.tokens_out,
            )

    def handler(request):
        sse = (
            'data: {"choices":[{"delta":'
            '{"content":"hi","reasoning_content":"thinking"}}]}\n\n'
            'data: {"choices":[{"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    _patch_httpx(monkeypatch, handler)
    eng = _ReasoningCapture()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.text == "hi|reasoning=thinking"


def test_default_dispatch_skips_malformed_json_chunks(monkeypatch) -> None:
    """Malformed JSON chunks must be skipped, not crash."""
    def handler(request):
        sse = (
            'data: {malformed json\n\n'
            'data: {"choices":[{"delta":{"content":"good"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is True
    assert resp.text == "good"


def test_default_dispatch_skips_non_data_prefix_lines(monkeypatch) -> None:
    """SSE comment lines (``: ...``) and other non-data prefixes must
    be skipped silently."""
    def handler(request):
        sse = (
            ': this is a comment line\n\n'
            'event: ping\n\n'
            'data: {"choices":[{"delta":{"content":"X"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    resp = eng.dispatch("hi", "test-model", {})
    assert resp.success is True
    assert resp.text == "X"


def test_dispatch_passes_stream_true_through_payload(monkeypatch) -> None:
    """The base class sets ``stream=True`` on every payload — even when
    the subclass's ``_build_payload`` doesn't include it."""
    captured: dict = {}

    def handler(request):
        captured["body"] = request.content
        sse = b'data: [DONE]\n\n'
        return httpx.Response(200, content=sse)

    _patch_httpx(monkeypatch, handler)
    eng = _MinimalTransport()
    eng.dispatch("hi", "test-model", {})
    import json
    body = json.loads(captured["body"])
    assert body.get("stream") is True
