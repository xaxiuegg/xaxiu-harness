"""Boundary tests for ``src.harness.engines.guards`` (Wave B/2)."""

from __future__ import annotations

import pytest

from harness.engines.base import EngineResponse
from harness.engines.guards import (
    AnchorReport,
    _normalize_text,
    anchor_fuzzy_check,
    classify_response,
    should_split_kimi_bundle,
    split_multi_domain_packet,
)


# ---------------------------------------------------------------------------
# classify_response — Rule 1: DeepSeek v4-flash packet trap
# ---------------------------------------------------------------------------

PACKET_TRAP_JSON = (
    '{"name": "edit_file", "arguments": {"file_path": "foo.py", "content": "bar"}}'
)

PACKET_TRAP_DSML = (
    '<function_calls>\n'
    '<invoke name="Edit">\n'
    '<parameter name="file_path">foo.py</parameter>\n'
    '</invoke>'
)


def test_classify_response_packet_trap_positive() -> None:
    resp = EngineResponse(success=True, text=PACKET_TRAP_JSON, latency_ms=100)
    result = classify_response(
        backend="deepseek", model="deepseek-v4-flash", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "packet_trap"
    assert result.text == PACKET_TRAP_JSON


def test_classify_response_packet_trap_negative_prose_in_fence() -> None:
    """Prose mentioning <function_calls> inside a markdown block must NOT flag."""
    text = (
        "Here is an example:\n\n"
        "```xml\n"
        "<function_calls>\n"
        '<invoke name="Edit">\n'
        "```\n\n"
        "This is just documentation."
    )
    resp = EngineResponse(success=True, text=text, latency_ms=100)
    result = classify_response(
        backend="deepseek", model="deepseek-v4-flash", packet_content="", response=resp
    )
    assert result is resp  # unchanged


def test_classify_response_packet_trap_negative_no_name() -> None:
    """JSON without 'name' key should not flag."""
    text = '{"arguments": {"x": 1}}'
    resp = EngineResponse(success=True, text=text, latency_ms=100)
    result = classify_response(
        backend="deepseek", model="deepseek-v4-flash", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_packet_trap_negative_no_arguments() -> None:
    """JSON without 'arguments' key should not flag."""
    text = '{"name": "foo"}'
    resp = EngineResponse(success=True, text=text, latency_ms=100)
    result = classify_response(
        backend="deepseek", model="deepseek-v4-flash", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_packet_trap_negative_not_flash() -> None:
    """Non-flash DeepSeek model should not flag."""
    resp = EngineResponse(success=True, text=PACKET_TRAP_JSON, latency_ms=100)
    result = classify_response(
        backend="deepseek", model="deepseek-chat", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_packet_trap_negative_backend() -> None:
    """Non-deepseek backend should not flag even with flash model."""
    resp = EngineResponse(success=True, text=PACKET_TRAP_JSON, latency_ms=100)
    result = classify_response(
        backend="kimi", model="kimi-v4-flash", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_packet_trap_negative_model_none() -> None:
    """None model should not flag."""
    resp = EngineResponse(success=True, text=PACKET_TRAP_JSON, latency_ms=100)
    result = classify_response(
        backend="deepseek", model=None, packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_packet_trap_edge_10kb() -> None:
    """Very long output starting with JSON should still flag."""
    big = '{"name": "x", "arguments": ' + "{" * 5000 + "}" * 5000
    resp = EngineResponse(success=True, text=big, latency_ms=100)
    result = classify_response(
        backend="deepseek", model="deepseek-v4-flash", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "packet_trap"


# ---------------------------------------------------------------------------
# classify_response — Rule 2: Kimi empty / XML
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "   ", "\n", "\t\n \r"])
def test_classify_response_kimi_empty_positive(text: str) -> None:
    resp = EngineResponse(success=True, text=text, latency_ms=50)
    result = classify_response(
        backend="kimi", model="kimi-k2", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "kimi_empty_or_xml"


def test_classify_response_kimi_xml_positive() -> None:
    text = '<?xml version="1.0" encoding="UTF-8"?><root/>'
    resp = EngineResponse(success=True, text=text, latency_ms=50)
    result = classify_response(
        backend="kimi", model="kimi-k2", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "kimi_empty_or_xml"


def test_classify_response_kimi_xml_with_leading_whitespace() -> None:
    text = '  \n  <?xml version="1.0"?><data/>'
    resp = EngineResponse(success=True, text=text, latency_ms=50)
    result = classify_response(
        backend="kimi", model="kimi-k2", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "kimi_empty_or_xml"


def test_classify_response_kimi_empty_negative() -> None:
    resp = EngineResponse(success=True, text="OK.", latency_ms=50)
    result = classify_response(
        backend="kimi", model="kimi-k2", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_kimi_xml_mentioned_not_preamble() -> None:
    """XML mentioned later in text, not at start, should not flag."""
    text = "The response starts here.\n<?xml version=\"1.0\"?>\nrest"
    resp = EngineResponse(success=True, text=text, latency_ms=50)
    result = classify_response(
        backend="kimi", model="kimi-k2", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_kimi_empty_negative_backend() -> None:
    """Empty response from non-kimi backend should not flag."""
    resp = EngineResponse(success=True, text="", latency_ms=50)
    result = classify_response(
        backend="anthropic", model="claude-sonnet", packet_content="", response=resp
    )
    assert result is resp


# ---------------------------------------------------------------------------
# classify_response — Rule 3: Anthropic refusal
# ---------------------------------------------------------------------------

REFUSAL_VARIANTS = [
    "I cannot help with that.",
    "I can't assist with this request.",
    "I won't generate that content.",
    "I am unable to comply.",
    "i cannot do this for you.",  # case-insensitive
]


@pytest.mark.parametrize("text", REFUSAL_VARIANTS)
def test_classify_response_anthropic_refusal_positive(text: str) -> None:
    resp = EngineResponse(success=True, text=text, latency_ms=75)
    result = classify_response(
        backend="anthropic", model="claude-sonnet", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "anthropic_refusal"


def test_classify_response_anthropic_refusal_after_500_chars() -> None:
    """Refusal appearing after the first 500 chars must NOT flag."""
    prefix = "A" * 500
    text = prefix + "I cannot help with that."
    resp = EngineResponse(success=True, text=text, latency_ms=75)
    result = classify_response(
        backend="anthropic", model="claude-sonnet", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_anthropic_refusal_negative() -> None:
    resp = EngineResponse(success=True, text="Here is the code you requested.", latency_ms=75)
    result = classify_response(
        backend="anthropic", model="claude-sonnet", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_anthropic_refusal_negative_backend() -> None:
    """Refusal text from non-anthropic backend should not flag."""
    resp = EngineResponse(success=True, text="I cannot help with that.", latency_ms=75)
    result = classify_response(
        backend="kimi", model="kimi-k2", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_anthropic_refusal_exactly_at_500_boundary() -> None:
    """Refusal starting exactly within the first 500 chars must flag."""
    prefix = "X" * 480
    text = prefix + "I cannot help with that."
    assert len(text) > 500
    resp = EngineResponse(success=True, text=text, latency_ms=75)
    result = classify_response(
        backend="anthropic", model="claude-sonnet", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "anthropic_refusal"


# ---------------------------------------------------------------------------
# classify_response — Rule 4: MiMo silent-empty (W4-J 2026-05-22)
# ---------------------------------------------------------------------------

def test_classify_response_mimo_empty_positive() -> None:
    """W4-G campaign found MiMo Pro returning success=True text='' on 3/5."""
    resp = EngineResponse(success=True, text="", latency_ms=22000)
    result = classify_response(
        backend="mimo", model="mimo-v2.5-pro", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "mimo_empty"


def test_classify_response_mimo_empty_whitespace_only() -> None:
    """Whitespace-only response is still empty for our purposes."""
    resp = EngineResponse(success=True, text="   \n\t  ", latency_ms=20000)
    result = classify_response(
        backend="mimo", model="mimo-v2.5", packet_content="", response=resp
    )
    assert result.success is False
    assert result.error == "mimo_empty"


def test_classify_response_mimo_empty_negative_with_content() -> None:
    """Real MiMo content must NOT flag."""
    resp = EngineResponse(success=True, text="here's your answer", latency_ms=15000)
    result = classify_response(
        backend="mimo", model="mimo-v2.5-pro", packet_content="", response=resp
    )
    assert result is resp


def test_classify_response_mimo_empty_negative_other_backend() -> None:
    """Empty text from non-MiMo backend should not flag as mimo_empty."""
    resp = EngineResponse(success=True, text="", latency_ms=10)
    result = classify_response(
        backend="deepseek", model="deepseek-chat", packet_content="", response=resp
    )
    # DeepSeek empty doesn't trip Rule 4; falls through to "no match"
    assert result is resp


# ---------------------------------------------------------------------------
# classify_response — Rule 5: no match (pass-through)
# ---------------------------------------------------------------------------

def test_classify_response_no_match_returns_original() -> None:
    resp = EngineResponse(success=True, text="All good.", latency_ms=10)
    result = classify_response(
        backend="deepseek", model="deepseek-chat", packet_content="", response=resp
    )
    assert result is resp


# ---------------------------------------------------------------------------
# should_split_kimi_bundle
# ---------------------------------------------------------------------------

def _make_packet(headings: list[str], padding: str = "") -> str:
    lines = []
    for h in headings:
        lines.append(f"## {h}")
        lines.append(f"content for {h}")
    text = "\n".join(lines)
    if padding:
        text += "\n" + padding
    return text


def test_should_split_kimi_bundle_positive() -> None:
    """Two distinct headings and >8 KiB must return True."""
    big = "x" * 9000
    packet = _make_packet(["Domain A", "Domain B"], padding=big)
    assert should_split_kimi_bundle(packet) is True


def test_should_split_kimi_bundle_negative_single_heading() -> None:
    packet = _make_packet(["Only One"], padding="y" * 9000)
    assert should_split_kimi_bundle(packet) is False


def test_should_split_kimi_bundle_negative_under_size() -> None:
    packet = _make_packet(["A", "B"], padding="z" * 100)
    assert should_split_kimi_bundle(packet) is False


def test_should_split_kimi_bundle_edge_exactly_8kb() -> None:
    """Exactly 8192 bytes with two headings must return False."""
    headings = "## A\n\n## B\n\n"
    padding = "p" * (8192 - len(headings.encode("utf-8")))
    packet = headings + padding
    assert len(packet.encode("utf-8")) == 8192
    assert should_split_kimi_bundle(packet) is False


def test_should_split_kimi_bundle_edge_just_over_8kb() -> None:
    """8193 bytes with two headings must return True."""
    headings = "## A\n\n## B\n\n"
    padding = "p" * (8193 - len(headings.encode("utf-8")))
    packet = headings + padding
    assert len(packet.encode("utf-8")) == 8193
    assert should_split_kimi_bundle(packet) is True


def test_should_split_kimi_bundle_duplicate_headings_count_once() -> None:
    """Duplicate headings should count as one distinct heading."""
    packet = _make_packet(["A", "A", "B"], padding="q" * 9000)
    assert should_split_kimi_bundle(packet) is True


def test_should_split_kimi_bundle_empty() -> None:
    assert should_split_kimi_bundle("") is False


def test_should_split_kimi_bundle_unicode_size() -> None:
    """Multi-byte UTF-8 characters must be counted correctly."""
    # Each 中 is 3 bytes in UTF-8
    padding = "中" * 3000  # 9000 bytes
    packet = "## A\n\n## B\n\n" + padding
    assert should_split_kimi_bundle(packet) is True


# ---------------------------------------------------------------------------
# split_multi_domain_packet
# ---------------------------------------------------------------------------

def test_split_multi_domain_packet_basic() -> None:
    packet = (
        "Preamble line 1\n"
        "Preamble line 2\n"
        "## Section A\n"
        "Content A\n"
        "## Section B\n"
        "Content B\n"
    )
    result = split_multi_domain_packet(packet)
    assert len(result) == 2
    assert result[0].startswith("Preamble line 1\nPreamble line 2\n")
    assert "## Section A\n" in result[0]
    assert "## Section B\n" not in result[0]
    assert result[1].startswith("Preamble line 1\nPreamble line 2\n")
    assert "## Section B\n" in result[1]


def test_split_multi_domain_packet_no_headings() -> None:
    """Defensive: no headings returns the whole document."""
    packet = "Just some text without headings.\n"
    result = split_multi_domain_packet(packet)
    assert result == [packet]


def test_split_multi_domain_packet_single_heading() -> None:
    packet = (
        "Preamble\n"
        "## Only Section\n"
        "Content\n"
    )
    result = split_multi_domain_packet(packet)
    assert len(result) == 1
    assert result[0] == packet


def test_split_multi_domain_packet_preserves_line_endings() -> None:
    packet = "Preamble\r\n## A\r\nLine 1\r\n## B\r\nLine 2\r\n"
    result = split_multi_domain_packet(packet)
    assert len(result) == 2
    # Ensure original line endings are preserved
    assert "\r\n" in result[0]
    assert "\r\n" in result[1]


# ---------------------------------------------------------------------------
# anchor_fuzzy_check
# ---------------------------------------------------------------------------

def test_anchor_fuzzy_check_all_exact_low() -> None:
    report = anchor_fuzzy_check(
        response_text="The quick brown fox jumps.",
        anchors=["quick", "fox"],
    )
    assert report == AnchorReport(total=2, byte_exact=2, fuzzy_match=0, missing=0, risk="LOW")


def test_anchor_fuzzy_check_fuzzy_med() -> None:
    """Smart quotes and extra whitespace should match via fuzzy path."""
    report = anchor_fuzzy_check(
        response_text='The \u201cquick\u201d   brown   fox  jumps.',  # smart double quotes
        anchors=['"quick" brown'],  # straight quotes, single-space
    )
    assert report == AnchorReport(total=1, byte_exact=0, fuzzy_match=1, missing=0, risk="MED")


def test_anchor_fuzzy_check_missing_high() -> None:
    report = anchor_fuzzy_check(
        response_text="The quick brown fox jumps.",
        anchors=["quick", "cat"],
    )
    assert report == AnchorReport(total=2, byte_exact=1, fuzzy_match=0, missing=1, risk="HIGH")


def test_anchor_fuzzy_check_mixed_exact_and_fuzzy_med() -> None:
    report = anchor_fuzzy_check(
        response_text="hello world \u2018nice\u2019 day",  # smart single quotes
        anchors=["world", "'nice'"],  # straight single quotes
    )
    assert report == AnchorReport(total=2, byte_exact=1, fuzzy_match=1, missing=0, risk="MED")


def test_anchor_fuzzy_check_mixed_exact_and_missing_high() -> None:
    report = anchor_fuzzy_check(
        response_text="hello world",
        anchors=["world", "missing", "also_missing"],
    )
    assert report == AnchorReport(total=3, byte_exact=1, fuzzy_match=0, missing=2, risk="HIGH")


def test_anchor_fuzzy_check_empty_anchors() -> None:
    report = anchor_fuzzy_check(response_text="anything", anchors=[])
    assert report == AnchorReport(total=0, byte_exact=0, fuzzy_match=0, missing=0, risk="LOW")


def test_anchor_fuzzy_check_empty_response() -> None:
    report = anchor_fuzzy_check(response_text="", anchors=["foo"])
    assert report == AnchorReport(total=1, byte_exact=0, fuzzy_match=0, missing=1, risk="HIGH")


def test_anchor_fuzzy_check_unicode_anchors() -> None:
    report = anchor_fuzzy_check(
        response_text="café naïve résumé",
        anchors=["naïve", "résumé"],
    )
    assert report == AnchorReport(total=2, byte_exact=2, fuzzy_match=0, missing=0, risk="LOW")


def test_anchor_fuzzy_check_indent_drift() -> None:
    """Extra indentation should be collapsed by normalization."""
    report = anchor_fuzzy_check(
        response_text="    def foo():\n        pass",
        anchors=["def foo(): pass"],
    )
    assert report == AnchorReport(total=1, byte_exact=0, fuzzy_match=1, missing=0, risk="MED")


def test_anchor_fuzzy_check_partial_boundary() -> None:
    """Anchor that is a substring at a word boundary."""
    report = anchor_fuzzy_check(
        response_text="foobar",
        anchors=["foo", "bar"],
    )
    # Both are substrings, so they match byte-exactly
    assert report == AnchorReport(total=2, byte_exact=2, fuzzy_match=0, missing=0, risk="LOW")


# ---------------------------------------------------------------------------
# _normalize_text (direct unit tests)
# ---------------------------------------------------------------------------

def test_normalize_text_smart_quotes() -> None:
    raw = "\u2018hello\u2019 \u201cworld\u201d"
    assert _normalize_text(raw) == "'hello' \"world\""


def test_normalize_text_collapse_whitespace() -> None:
    raw = "a\n\n\tb\r\n   c"
    assert _normalize_text(raw) == "a b c"


def test_normalize_text_strip() -> None:
    assert _normalize_text("  hello  ") == "hello"


def test_normalize_text_empty() -> None:
    assert _normalize_text("") == ""


def test_normalize_text_unicode_unchanged() -> None:
    assert _normalize_text("café") == "café"
