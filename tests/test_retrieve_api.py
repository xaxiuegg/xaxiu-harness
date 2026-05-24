"""W11-RETRIEVE-API: tests for `harness.retrieve(dispatch_id, scope=...)`.

Reads from the dispatch_cache (populated by W11-CONTEXT-FRUGAL-RETURN-LAZY)
keyed by dispatch_id.  Three scopes: summary (cheap), full (burns context),
chunks (paginated for RAG-style retrieval).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import harness
from harness.engines import dispatch_cache as dc


@pytest.fixture
def cached_dispatch(tmp_path):
    """Set up a known dispatch payload in tmp_path's cache."""
    full_text = (
        "This is the complete dispatch response with multiple paragraphs.\n"
        "\n"
        "Line two has more content here that the agent might need.\n"
        "Line three explains the resolution.\n"
        "...\n"
        "Final line with the conclusion."
    )
    payload = {
        "dispatch_id": "test-disp-001",
        "engine_used": "kimi",
        "fallback_chain": ["kimi"],
        "full_text": full_text,
        "summary": "head+tail of the full text (~200 chars)",
        "tokens_in": 50,
        "tokens_out": 100,
        "cost_usd": 0.0,
    }
    dc.store_for_retrieve("test-disp-001", payload, project_root=tmp_path)
    return tmp_path, full_text


# -- scope="summary" (the cheap default) ---------------------------------


def test_retrieve_summary_returns_cached_summary(cached_dispatch):
    project_root, _ = cached_dispatch
    result = harness.retrieve(
        "test-disp-001", scope="summary",
        project_root=str(project_root),
    )
    assert result == "head+tail of the full text (~200 chars)"


def test_retrieve_default_scope_is_summary(cached_dispatch):
    project_root, _ = cached_dispatch
    result = harness.retrieve(
        "test-disp-001", project_root=str(project_root),
    )
    # Default scope is "summary"
    assert "head+tail" in result


# -- scope="full" (loads full text into agent context) -------------------


def test_retrieve_full_returns_complete_text(cached_dispatch):
    project_root, full_text = cached_dispatch
    result = harness.retrieve(
        "test-disp-001", scope="full",
        project_root=str(project_root),
    )
    assert result == full_text


# -- scope="chunks" (RAG-style paginated read) ---------------------------


def test_retrieve_chunks_returns_list(cached_dispatch):
    project_root, _ = cached_dispatch
    result = harness.retrieve(
        "test-disp-001", scope="chunks",
        chunk_size_tokens=10,  # small chunks for testing
        project_root=str(project_root),
    )
    assert isinstance(result, list)
    assert all(isinstance(c, str) for c in result)
    assert len(result) >= 1


def test_retrieve_chunks_reassemble_to_full_text(cached_dispatch):
    """Joining chunks reproduces the original text."""
    project_root, full_text = cached_dispatch
    chunks = harness.retrieve(
        "test-disp-001", scope="chunks",
        chunk_size_tokens=20,
        project_root=str(project_root),
    )
    assert "".join(chunks) == full_text


def test_retrieve_chunks_respects_chunk_size(cached_dispatch):
    project_root, full_text = cached_dispatch
    # chunk_size_tokens=10 → ~40 char chunks
    chunks = harness.retrieve(
        "test-disp-001", scope="chunks",
        chunk_size_tokens=10,
        project_root=str(project_root),
    )
    # All non-final chunks should be 40 chars
    for chunk in chunks[:-1]:
        assert len(chunk) == 40, (
            f"non-final chunk has wrong size: {len(chunk)} (expected 40)"
        )


def test_retrieve_chunks_handles_small_text(cached_dispatch):
    """Text shorter than one chunk -> single-element list."""
    project_root, _ = cached_dispatch
    # Use chunk size larger than the full text
    chunks = harness.retrieve(
        "test-disp-001", scope="chunks",
        chunk_size_tokens=10000,
        project_root=str(project_root),
    )
    assert len(chunks) == 1


# -- Error cases ---------------------------------------------------------


def test_retrieve_missing_id_raises_result_not_found(tmp_path):
    with pytest.raises(harness.ResultNotFoundError,
                       match="never ran|cache was cleared|wrong project_root"):
        harness.retrieve("does-not-exist", project_root=str(tmp_path))


def test_retrieve_invalid_scope_raises_value_error(cached_dispatch):
    project_root, _ = cached_dispatch
    with pytest.raises(ValueError, match="unknown scope"):
        harness.retrieve(
            "test-disp-001", scope="invalid-scope",  # type: ignore[arg-type]
            project_root=str(project_root),
        )


def test_retrieve_corrupted_missing_summary_raises_corrupted(tmp_path):
    """Cached payload missing 'summary' field -> ResultCorruptedError."""
    dc.store_for_retrieve("corrupted-disp", {
        "dispatch_id": "corrupted-disp",
        # 'summary' key missing
        "full_text": "ok",
    }, project_root=tmp_path)
    with pytest.raises(harness.ResultCorruptedError,
                       match="missing 'summary'"):
        harness.retrieve(
            "corrupted-disp", scope="summary",
            project_root=str(tmp_path),
        )


def test_retrieve_corrupted_missing_full_text_raises_corrupted(tmp_path):
    dc.store_for_retrieve("corrupted-disp-2", {
        "dispatch_id": "corrupted-disp-2",
        "summary": "ok",
        # 'full_text' key missing
    }, project_root=tmp_path)
    with pytest.raises(harness.ResultCorruptedError,
                       match="missing 'full_text'"):
        harness.retrieve(
            "corrupted-disp-2", scope="full",
            project_root=str(tmp_path),
        )


# -- Integration: dispatch_id from a real DispatchResult round-trips -----


def test_retrieve_works_with_dispatch_id_from_DispatchResult(tmp_path, monkeypatch):
    """End-to-end: simulate the dispatcher's cache-write, then retrieve."""
    monkeypatch.chdir(tmp_path)
    # Mimic what dispatcher.dispatch_packet writes on success
    full_text = "engine response: the answer is 42"
    payload = {
        "dispatch_id": "e2e-disp",
        "engine_used": "kimi",
        "full_text": full_text,
        "summary": "answer is 42",
        "tokens_in": 5,
        "tokens_out": 10,
        "cost_usd": 0.0,
    }
    dc.store_for_retrieve("e2e-disp", payload)
    # Agent calls retrieve()
    assert harness.retrieve("e2e-disp", scope="summary") == "answer is 42"
    assert harness.retrieve("e2e-disp", scope="full") == full_text


# -- The agent's expected workflow --------------------------------------


def test_typical_agent_workflow_check_summary_then_full(cached_dispatch):
    """Agent's typical pattern: cheap summary check first; only burn
    context on .full if the summary signals it's needed."""
    project_root, full_text = cached_dispatch
    summary = harness.retrieve("test-disp-001", scope="summary",
                               project_root=str(project_root))
    # Agent decides based on summary
    if "head+tail" in summary:
        # Yes, more detail needed
        full = harness.retrieve("test-disp-001", scope="full",
                                project_root=str(project_root))
        assert full == full_text
