"""W7-MUTATION-CONCRETE: real-assertion tests that kill concrete.py
mutations the W6-A3 sweep found (1.0 kill rate).

W6-A3 sweep on src/harness/engines/concrete.py:
  - eq_to_neq               failed=1 (line 138 `block.get("type") == "text"`)
  - is_not_none_to_is_none  failed=1 (line 257 `usage_info is not None`)
  - bool_return_flip        skipped (no literal `return True`)
  - gt_to_ge                skipped (no ` > 0` pattern)
  - plus1_to_minus1         skipped (no ` + 1` pattern)

This file pushes the avg above the 3-kill threshold by targeting the
catchable mutations directly.
"""

from __future__ import annotations

from typing import Any

import pytest

import httpx

from harness.engines.concrete import (
    _extract_anthropic_text,
    _extract_openai_usage,
    _extract_anthropic_usage,
)

# Capture the un-patched httpx.Client so the MockTransport stubs don't
# recurse through the patched symbol.
_ORIGINAL_HTTPX_CLIENT = httpx.Client


# ===========================================================================
# Kill `block.get("type") == "text"` mutation (line 138)
# ===========================================================================


def test_extract_anthropic_text_single_text_block() -> None:
    """Mutation: `block.get("type") == "text"` → `!= "text"`.

    Under the mutation, the function would SKIP the text block and
    return "" instead of the actual text content.
    """
    response = {"content": [{"type": "text", "text": "Hello, world."}]}
    assert _extract_anthropic_text(response) == "Hello, world."


def test_extract_anthropic_text_skips_tool_use_blocks() -> None:
    """When content has both tool_use AND text blocks, the function
    must skip tool_use and return the text block's content.  Under
    the mutation, it would skip text and return "" (or worse,
    accidentally return the tool_use block's text field if present).
    """
    response = {"content": [
        {"type": "tool_use", "id": "tu_1", "name": "calc",
         "input": {"x": 1}, "text": "WRONG"},
        {"type": "text", "text": "RIGHT"},
    ]}
    assert _extract_anthropic_text(response) == "RIGHT", (
        "must return the text-block content, not the tool_use block; "
        "under == → != mutation, this would return 'WRONG' or ''"
    )


def test_extract_anthropic_text_only_tool_use_returns_empty() -> None:
    """No text blocks → empty string.  Under mutation, the tool_use
    block would match (its type != "text") and return its text field
    (if present) — a wrong behavior."""
    response = {"content": [
        {"type": "tool_use", "id": "tu_1", "name": "x",
         "input": {}, "text": "tool_text_should_not_leak"},
    ]}
    assert _extract_anthropic_text(response) == "", (
        "tool-only responses must return empty string; under mutation "
        "the tool_use block would match and leak its text field"
    )


def test_extract_anthropic_text_multiple_text_blocks_first_wins() -> None:
    """When multiple text blocks present, return the FIRST.  Catches
    mutation flipping the loop order or the equality check."""
    response = {"content": [
        {"type": "text", "text": "FIRST"},
        {"type": "text", "text": "SECOND"},
    ]}
    assert _extract_anthropic_text(response) == "FIRST"


def test_extract_anthropic_text_empty_content_list() -> None:
    """Edge: empty content list → "".  Catches off-by-one or boundary
    mutations in the early-exit guard at line 134."""
    assert _extract_anthropic_text({"content": []}) == ""
    assert _extract_anthropic_text({}) == ""  # no key at all


# ===========================================================================
# Kill `usage_info is not None` mutation (line 257) — via DeepSeek dispatch
# ===========================================================================
#
# Direct unit test on the function-level guard isn't possible because
# the `parsed_anything` check is INSIDE DeepSeekConcrete.dispatch.  We
# need to invoke dispatch with a mocked SSE stream that exercises
# exactly the "only usage, no content, no finish_reason" path.


@pytest.fixture
def deepseek_engine(monkeypatch):
    """Build a DeepSeekConcrete without invoking the real abstract
    method machinery."""
    import httpx
    from harness.engines.concrete import DeepSeekConcrete
    monkeypatch.setattr(DeepSeekConcrete, "__abstractmethods__", frozenset())

    class _T(DeepSeekConcrete):
        name = "deepseek"

        def __init__(self, key: str) -> None:
            self._api_key = key

    return _T("deepseek-key")


def test_deepseek_parsed_anything_with_usage_only_succeeds(
    monkeypatch, deepseek_engine
) -> None:
    """Mutation: `usage_info is not None` → `is None`.

    Original: usage block makes parsed_anything=True → success.
    Mutated: usage block makes parsed_anything=(False because the
    usage_info IS NOT None) → falls to other contributors.  When
    content + finish_reason are also empty, mutated parsed_anything
    is False → returns parse_error_no_chunks.

    This test sets up the exact case: SSE with ONLY a usage chunk and
    NO content + NO finish_reason.  Original behavior: success=True
    with empty text.  Mutated behavior: success=False.
    """
    import httpx

    def handler(request):
        # SSE with usage_only — no content delta, no finish_reason
        sse = (
            'data: {"choices":[{}],"usage":{"prompt_tokens":10,'
            '"completion_tokens":0}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = deepseek_engine.dispatch("hi", "deepseek-v4-flash", {})
    assert resp.success is True, (
        f"usage-only stream should succeed (parsed_anything via "
        f"usage_info is not None); got success={resp.success} "
        f"error={resp.error}.  Under mutation, this becomes success=False."
    )
    assert resp.text == ""


def test_deepseek_parsed_anything_with_finish_reason_only_succeeds(
    monkeypatch, deepseek_engine
) -> None:
    """Sentinel for the parsed_anything OR-chain: finish_reason ALONE
    should also make parsed_anything=True.  This catches mutations
    that flip the OR to AND or that drop the finish_reason check."""
    import httpx

    def handler(request):
        sse = (
            'data: {"choices":[{"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = deepseek_engine.dispatch("hi", "deepseek-v4-flash", {})
    assert resp.success is True


def test_deepseek_parsed_anything_with_content_only_succeeds(
    monkeypatch, deepseek_engine
) -> None:
    """Sentinel: content alone (no usage, no finish_reason) still
    succeeds.  Catches mutations that require usage_info to be
    present."""
    import httpx

    def handler(request):
        sse = (
            'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = deepseek_engine.dispatch("hi", "deepseek-v4-flash", {})
    assert resp.success is True
    assert resp.text == "hi"


def test_deepseek_no_chunks_no_usage_returns_parse_error(
    monkeypatch, deepseek_engine
) -> None:
    """Empty SSE stream → parse_error_no_chunks.  Catches mutations
    that flip the early-return guard."""
    import httpx

    def handler(request):
        return httpx.Response(200, content=b"")

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = deepseek_engine.dispatch("hi", "deepseek-v4-flash", {})
    assert resp.success is False
    assert resp.error == "parse_error_no_chunks"


# ===========================================================================
# Kill `data_str == "[DONE]"` mutation (line 235) — DeepSeek SSE terminator
# ===========================================================================
# Even though str.replace(count=1) only hits the FIRST ` == `, future
# script revisions may use a different strategy.  These tests guard the
# secondary occurrence at line 235.


def test_deepseek_sse_done_terminator_stops_parsing(
    monkeypatch, deepseek_engine
) -> None:
    """Mutation: `data_str == "[DONE]"` → `!= "[DONE]"`.

    Original: [DONE] breaks the loop.  Mutated: ANY data_str except
    [DONE] would break the loop — including the first data: chunk,
    which would drop all content.
    """
    import httpx

    def handler(request):
        # Stream emits content THEN [DONE].  Under mutation, the first
        # chunk (which has content) would break the loop before parsing,
        # dropping the content entirely.
        sse = (
            'data: {"choices":[{"delta":{"content":"part1"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"part2"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    )

    resp = deepseek_engine.dispatch("hi", "deepseek-v4-flash", {})
    assert resp.success is True
    # Both chunks should be aggregated; under the mutation, the first
    # chunk would break the loop, returning success=False (no parseable
    # data) — OR the chunk would be parsed but the LOOP termination
    # would invert.
    assert resp.text == "part1part2", (
        f"both chunks should aggregate; got {resp.text!r}.  "
        f"Under [DONE] terminator mutation, parsing would invert."
    )


def test_extract_openai_usage_returns_zero_on_missing_usage() -> None:
    """Sentinel for the usage helper.  Catches mutations on the usage
    type-check or default values.  Under various mutations
    (e.g. `isinstance(usage, dict)` flips), the function might return
    non-zero defaults or crash."""
    # Missing usage block entirely
    assert _extract_openai_usage({}) == (0, 0)
    # usage present but None
    assert _extract_openai_usage({"usage": None}) == (0, 0)
    # usage is wrong type (string)
    assert _extract_openai_usage({"usage": "garbage"}) == (0, 0)
    # usage dict but values missing
    assert _extract_openai_usage({"usage": {}}) == (0, 0)


def test_extract_openai_usage_returns_split_when_populated() -> None:
    """Standard happy path: usage has both prompt_tokens and
    completion_tokens.  Catches mutations on the int() coercion or
    the .get(default=0)."""
    out = _extract_openai_usage({"usage": {
        "prompt_tokens": 42, "completion_tokens": 95,
    }})
    assert out == (42, 95)


def test_extract_anthropic_usage_returns_zero_on_missing_usage() -> None:
    """Same sentinel pattern for Anthropic usage helper.  Anthropic
    uses input_tokens/output_tokens keys (different from OpenAI's
    prompt_tokens/completion_tokens)."""
    assert _extract_anthropic_usage({}) == (0, 0)
    assert _extract_anthropic_usage({"usage": None}) == (0, 0)


def test_extract_anthropic_usage_returns_split_when_populated() -> None:
    out = _extract_anthropic_usage({"usage": {
        "input_tokens": 30, "output_tokens": 40,
    }})
    assert out == (30, 40)


# ===========================================================================
# Kill `len(reasoning_chunks) > 0` mutation (line 450, KimiConcrete)
# ===========================================================================
# This is a new pattern added by W7-KIMI-REASONING-EMPTY.  The sweep's
# gt_to_ge mutation hits this and is OBSERVABLE: under `>= 0`,
# reasoning_only=True whenever content_chunks=[] (even with no
# reasoning at all).  We catch by emitting a stream with usage_info
# ONLY (parsed_anything=True via usage, content empty, reasoning empty).


@pytest.fixture
def kimi_engine_min(monkeypatch):
    from harness.engines.concrete import KimiConcrete
    monkeypatch.setattr(KimiConcrete, "__abstractmethods__", frozenset())

    class _T(KimiConcrete):
        name = "kimi"

        def __init__(self, key: str) -> None:
            self._api_key = key

    return _T("kimi-key")


def test_kimi_reasoning_only_false_when_only_usage_no_content_no_reasoning(
    monkeypatch, kimi_engine_min
) -> None:
    """Mutation: `len(reasoning_chunks) > 0` → `>= 0` (always True).

    Under the mutation, reasoning_only would flip to True whenever
    content_chunks=[] — even when reasoning_chunks=[] too (a
    usage-only response that has nothing to do with reasoning).
    """
    import httpx

    def handler(request):
        # SSE: usage block only, no content, no reasoning, no finish
        sse = (
            'data:{"choices":[{}],"usage":'
            '{"prompt_tokens":10,"completion_tokens":0}}\n\n'
            'data:[DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(handler))
    )
    resp = kimi_engine_min.dispatch("hi", "kimi-model", {})
    assert resp.success is True  # usage_info makes parsed_anything True
    assert resp.text == ""
    assert resp.reasoning_only is False, (
        "reasoning_only must be False when reasoning_chunks=[]; "
        "under `>= 0` mutation it would become True for any "
        "empty-content response — a false retry signal."
    )


def test_kimi_reasoning_only_false_when_only_finish_reason(
    monkeypatch, kimi_engine_min
) -> None:
    """Sentinel for the same mutation: finish_reason alone (no
    content, no reasoning) still must NOT set reasoning_only=True."""
    import httpx

    def handler(request):
        sse = (
            'data:{"choices":[{"finish_reason":"stop"}]}\n\n'
            'data:[DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"))

    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _ORIGINAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(handler))
    )
    resp = kimi_engine_min.dispatch("hi", "kimi-model", {})
    assert resp.success is True
    assert resp.reasoning_only is False
