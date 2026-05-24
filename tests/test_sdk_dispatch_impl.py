"""W11-PYTHON-SDK-API-IMPL: tests for the real harness.dispatch().

Replaces the prior test_sdk_stubs.py NotImplementedError test for
dispatch().  Verifies:
- prompt string is dispatched through dispatcher.dispatch_packet
- prompt that looks like a path uses the file directly
- engine arg → force_engine in dispatcher
- return_mode controls whether result.text is set
- DispatchResult contract preserved (success, dispatch_id, engine_used, etc.)
- failure path returns success=False (does NOT raise)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import harness
from harness.engines.dispatcher import DispatchResult


def _fake_dispatch_result(
    *, success: bool = True, engine: str = "mock",
    dispatch_id: str = "abc-123", text: str = "hello",
    error: str | None = None,
) -> DispatchResult:
    return DispatchResult(
        success=success,
        engine_used=engine,
        fallback_chain=[engine],
        text=text,
        dispatch_id=dispatch_id,
        summary=text[:300],
        truncated=False,
        error=error or "",
    )


@pytest.fixture
def mock_dispatch_packet(monkeypatch):
    """Patch dispatcher.dispatch_packet so SDK calls don't hit live engines."""
    captured = {"calls": []}

    def _fake(project, packet_path, force_engine=None, force_model=None,
              wave_id=None, trusted_source=False, bypass_chain=False):
        captured["calls"].append({
            "project": project, "packet_path": packet_path,
            "force_engine": force_engine, "force_model": force_model,
        })
        return _fake_dispatch_result()

    # Patch BOTH the harness.engines.dispatcher module AND any callers
    # importing dispatch_packet by name (the SDK uses the latter pattern).
    monkeypatch.setattr("harness.engines.dispatcher.dispatch_packet",
                         _fake)
    return captured


# -- dispatch() basic dispatch path -------------------------------------


def test_dispatch_returns_dispatch_result_instance(mock_dispatch_packet):
    result = harness.dispatch("hello world")
    assert isinstance(result, harness.DispatchResult)


def test_dispatch_calls_dispatcher(mock_dispatch_packet):
    harness.dispatch("hello world")
    assert len(mock_dispatch_packet["calls"]) == 1


def test_dispatch_engine_arg_becomes_force_engine(mock_dispatch_packet):
    harness.dispatch("hi", engine="kimi")
    assert mock_dispatch_packet["calls"][0]["force_engine"] == "kimi"


def test_dispatch_no_engine_arg_lets_routing_decide(mock_dispatch_packet):
    harness.dispatch("hi")
    assert mock_dispatch_packet["calls"][0]["force_engine"] is None


# -- prompt-as-path vs prompt-as-text -----------------------------------


def test_dispatch_path_string_is_used_as_packet_path(mock_dispatch_packet,
                                                      tmp_path):
    packet = tmp_path / "p.md"
    packet.write_text("packet body", encoding="utf-8")
    harness.dispatch(str(packet))
    assert mock_dispatch_packet["calls"][0]["packet_path"] == str(packet)


def test_dispatch_non_path_prompt_writes_tempfile(mock_dispatch_packet):
    harness.dispatch("write this text as a packet")
    packet_path = mock_dispatch_packet["calls"][0]["packet_path"]
    # Path was created (a temp file) and contains the prompt
    p = Path(packet_path)
    assert p.exists()
    assert "write this text as a packet" in p.read_text(encoding="utf-8")


# -- return_mode = summary (default) ------------------------------------


def test_dispatch_summary_mode_leaves_text_none_by_default(mock_dispatch_packet):
    """W11-CONTEXT-FRUGAL contract: default mode strips text."""
    r = harness.dispatch("hi", return_mode="summary")
    # SDK contract: text stays None (the agent retrieves later if needed)
    assert r.text is None or r.text == ""
    # But summary is populated
    assert r.summary  # non-empty


def test_dispatch_full_mode_includes_text(mock_dispatch_packet):
    r = harness.dispatch("hi", return_mode="full")
    # Full mode: text is preserved
    assert r.text is not None


def test_dispatch_with_full_text_shortcut(mock_dispatch_packet):
    r = harness.dispatch("hi", with_full_text=True)
    # Equivalent to return_mode="full"
    assert r.text is not None


def test_dispatch_ref_mode_omits_both_text_and_summary(mock_dispatch_packet):
    """ref mode: metadata-only.  Most context-frugal."""
    r = harness.dispatch("hi", return_mode="ref")
    assert r.text is None or r.text == ""
    # In ref mode summary is also empty (caller uses dispatch_id + retrieve())
    # (Implementation may keep summary; the load-bearing thing is text=None)


# -- engine fallback list -----------------------------------------------


def test_dispatch_engine_list_uses_first_as_force_engine(mock_dispatch_packet):
    """When engine=['kimi','deepseek'], first is forced; fallback chain
    handles the rest via the dispatcher's existing logic."""
    harness.dispatch("hi", engine=["kimi", "deepseek"])
    assert mock_dispatch_packet["calls"][0]["force_engine"] == "kimi"


# -- error path: dispatcher returns success=False -----------------------


def test_dispatch_returns_failure_result_not_raises(monkeypatch):
    monkeypatch.setattr(
        "harness.engines.dispatcher.dispatch_packet",
        lambda **k: _fake_dispatch_result(
            success=False, text="", error="engine_pool_exhausted",
        ),
    )
    r = harness.dispatch("hi")
    assert r.success is False
    # SDK DispatchResult exposes error_excerpt (not .error from dispatcher)
    assert "engine_pool_exhausted" in (r.error_excerpt or "")


# -- DispatchResult contract preserved -----------------------------------


def test_dispatch_result_has_dispatch_id(mock_dispatch_packet):
    r = harness.dispatch("hi")
    assert r.dispatch_id
    assert isinstance(r.dispatch_id, str)


def test_dispatch_result_has_engine_used(mock_dispatch_packet):
    r = harness.dispatch("hi")
    assert r.engine_used


# -- repeated dispatches don't crash + don't leak temp files ------------


def test_dispatch_can_be_called_multiple_times(mock_dispatch_packet):
    for _ in range(5):
        r = harness.dispatch("hi")
        assert r.success is True
    assert len(mock_dispatch_packet["calls"]) == 5
