"""W11-CONTEXT-FRUGAL-RETURN-SCHEMA: tests for the new DispatchResult fields +
feature flag preserving backwards compat with existing callers.

This is the SAFE half of W11-CONTEXT-FRUGAL-RETURN.  Schema only;
lazy `.full()` fetch lives in W11-CONTEXT-FRUGAL-RETURN-LAZY (next
row).  The env flag HARNESS_DISPATCH_FULL_BY_DEFAULT=True is the
default and keeps existing dispatch callers (worker.py, integrator,
coord) unchanged.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from harness.engines.dispatcher import (
    DispatchResult,
    _dispatch_full_by_default,
    _extract_error_excerpt,
    _extract_summary,
)


# -- _extract_summary --


def test_extract_summary_empty_returns_empty():
    assert _extract_summary("") == ""
    assert _extract_summary(None) == ""  # defensive


def test_extract_summary_short_text_returns_verbatim():
    short = "Hello world"
    assert _extract_summary(short) == short


def test_extract_summary_long_text_truncates_with_marker():
    long = "\n".join(f"line {i}" for i in range(50))
    summary = _extract_summary(long)
    assert len(summary) <= 400  # well under typical 200K context cost
    # Tail preservation: last line MUST survive (key per panel C5)
    assert "line 49" in summary
    # Head preservation: first line too
    assert "line 0" in summary
    # Marker explains what was dropped
    assert "elided" in summary


def test_extract_summary_long_lines_truncated_with_middle_elision():
    """Pathological case: one super-long line that exceeds max_chars."""
    long_line = "A" * 5000
    summary = _extract_summary(long_line)
    # Should fall through to char-truncation path
    assert len(summary) <= 400
    # Should preserve head + tail of the long line
    assert summary.startswith("A")
    assert summary.endswith("A")


def test_extract_summary_respects_max_chars_param():
    long = "\n".join(f"line {i}" for i in range(50))
    summary = _extract_summary(long, max_chars=100)
    assert len(summary) <= 200  # 100 + some margin for elision marker


def test_extract_summary_strips_outer_whitespace():
    text = "\n\n  Hello  \n\n"
    assert _extract_summary(text) == "Hello"


# -- _extract_error_excerpt --


def test_extract_error_excerpt_none_returns_none():
    assert _extract_error_excerpt(None) is None
    assert _extract_error_excerpt("") is None


def test_extract_error_excerpt_short_returns_verbatim():
    assert _extract_error_excerpt("ConnectionError: refused") == "ConnectionError: refused"


def test_extract_error_excerpt_long_truncates_to_max_chars():
    long_err = "X" * 500
    excerpt = _extract_error_excerpt(long_err, max_chars=200)
    assert len(excerpt) == 200
    assert excerpt.endswith("...")


# -- DispatchResult schema (new fields with safe defaults) --


def test_dispatch_result_constructible_with_minimal_args():
    """Legacy callers (46 sites) don't need to know about new fields."""
    r = DispatchResult(
        success=True, engine_used="kimi", fallback_chain=["kimi"],
        text="response", error=None, dispatch_id="abc",
    )
    # New fields have safe defaults
    assert r.summary == ""
    assert r.truncated is False
    assert r.error_excerpt is None
    assert r.content_ref is None


def test_dispatch_result_accepts_new_fields_explicitly():
    r = DispatchResult(
        success=True, engine_used="kimi", fallback_chain=["kimi"],
        text="", error=None, dispatch_id="abc",
        summary="cached head+tail",
        truncated=True,
        content_ref="cache://abc",
    )
    assert r.summary == "cached head+tail"
    assert r.truncated is True
    assert r.content_ref == "cache://abc"


def test_dispatch_result_is_still_frozen():
    """DispatchResult is frozen=True; new fields don't break that."""
    r = DispatchResult(
        success=True, engine_used="kimi", fallback_chain=["kimi"],
        text="", error=None, dispatch_id="abc",
    )
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError subclass of Exception
        r.summary = "mutated"  # type: ignore[misc]


# -- _dispatch_full_by_default feature flag --


def test_dispatch_full_by_default_true_when_unset(monkeypatch):
    """Default value preserves pre-W11 behavior."""
    monkeypatch.delenv("HARNESS_DISPATCH_FULL_BY_DEFAULT", raising=False)
    assert _dispatch_full_by_default() is True


def test_dispatch_full_by_default_false_when_explicit(monkeypatch):
    monkeypatch.setenv("HARNESS_DISPATCH_FULL_BY_DEFAULT", "False")
    assert _dispatch_full_by_default() is False
    for v in ("0", "false", "FALSE", "no", "off", "Off"):
        monkeypatch.setenv("HARNESS_DISPATCH_FULL_BY_DEFAULT", v)
        assert _dispatch_full_by_default() is False, (
            f"value {v!r} should be falsey"
        )


def test_dispatch_full_by_default_true_when_truthy(monkeypatch):
    for v in ("1", "true", "True", "TRUE", "yes", "anything-else"):
        monkeypatch.setenv("HARNESS_DISPATCH_FULL_BY_DEFAULT", v)
        assert _dispatch_full_by_default() is True, (
            f"value {v!r} should be truthy (default-on)"
        )


# -- Backwards-compat: existing dispatch tests still work ----------------


def test_existing_dispatch_callers_unaffected_when_flag_default_true(monkeypatch):
    """The 46 existing callers construct DispatchResult without the new
    fields.  Defaults preserve their expected behavior."""
    monkeypatch.delenv("HARNESS_DISPATCH_FULL_BY_DEFAULT", raising=False)
    # Construct as a legacy caller would (no new field knowledge)
    r = DispatchResult(
        success=True, engine_used="kimi", fallback_chain=["kimi"],
        text="full response body", error=None, dispatch_id="abc",
        tokens_used=100, cost_usd=0.001, tokens_in=50, tokens_out=50,
    )
    # All legacy fields work as before
    assert r.success is True
    assert r.text == "full response body"
    assert r.tokens_used == 100
    # New fields don't perturb legacy behavior — they're default-empty
    assert r.summary == ""
    assert r.truncated is False
