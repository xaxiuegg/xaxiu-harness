"""W13-DOC-SDK-COVERAGE: CI gate ensuring docs reference every public SDK name.

Symmetric twin of ``tests/test_docs_no_future_as_present.py``:

- That gate fails if docs reference a CLI verb that doesn't exist
  (catches forward-looking hallucination — "we have ``harness foo``"
  when we don't).
- THIS gate fails if ``harness.__all__`` adds a public name that the
  agent-facing docs don't mention (catches backward-looking drift —
  "we shipped ``harness.review()`` but the quickstart still only
  documents the original 3 SDK fns").

Together they bound doc drift in both directions: the docs cannot
overpromise nor underpromise relative to the binary.

Motivation: a fresh agent reading AGENT_QUICKSTART.md and trusting it
must not miss real SDK capabilities.  Caught in the 2026-05-25 review:
``review`` and ``capabilities`` had shipped but the quickstart's
section 10 API surface table still listed only dispatch / retrieve /
budget_status.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
QUICKSTART = REPO_ROOT / "docs" / "AGENT_QUICKSTART.md"

# Names in __all__ that don't need their own doc mention.  Type aliases
# and exception subclasses are conventionally documented as part of the
# function signatures that use them, so we don't require an isolated
# mention.  When you add a new exception or alias to __all__, add it
# here too if it doesn't warrant its own callout.
NAMES_DOCUMENTED_BY_REFERENCE = {
    "__version__",     # implied by every doc/code example
    "ReturnMode",      # type alias used by dispatch()'s signature
    "RetrieveScope",   # type alias used by retrieve()'s signature
}


def _public_sdk_names() -> list[str]:
    """Read the runtime SDK __all__ list — this IS the contract."""
    import harness
    return list(harness.__all__)


def _quickstart_text() -> str:
    """Read the quickstart as plain text for substring scans."""
    assert QUICKSTART.exists(), f"missing {QUICKSTART} (relative to repo root)"
    return QUICKSTART.read_text(encoding="utf-8")


def test_quickstart_exists() -> None:
    """Sanity: the doc file is present."""
    assert QUICKSTART.exists(), (
        f"docs/AGENT_QUICKSTART.md is missing.  This is the load-bearing "
        f"fresh-agent onboarding doc; CI must not pass without it."
    )


def test_quickstart_mentions_every_public_sdk_name() -> None:
    """Every name in ``harness.__all__`` (except by-reference ones) must
    appear at least once in AGENT_QUICKSTART.md.

    The check is a plain substring match — the doc can mention the name
    in prose, in a code block, or in a signature; all count.  A real
    code example is strongly preferred but not required by this gate
    (the gate is a coverage floor, not a quality measure).
    """
    text = _quickstart_text()
    missing: list[str] = []
    for name in _public_sdk_names():
        if name in NAMES_DOCUMENTED_BY_REFERENCE:
            continue
        if name not in text:
            missing.append(name)
    assert not missing, (
        f"AGENT_QUICKSTART.md is missing references to public SDK "
        f"names: {missing}\n\n"
        f"Either: (a) add a brief code example / signature to the "
        f"quickstart so a fresh agent learns the surface, OR (b) if "
        f"the name truly doesn't warrant a callout (type alias, "
        f"exception used only by reference), add it to "
        f"NAMES_DOCUMENTED_BY_REFERENCE in this test with a comment."
    )


def test_quickstart_documents_dispatch_signature() -> None:
    """Hard guarantee: the dispatch() signature appears in the doc.

    dispatch() is THE load-bearing entry point; a typo / signature
    drift here cascades into every agent's first interaction with
    the harness.  This is a tighter check than the substring scan.
    """
    text = _quickstart_text()
    # The signature snippet from section 10 — drift here is a real bug
    assert "dispatch(prompt" in text, (
        "AGENT_QUICKSTART.md missing the dispatch() signature.  "
        "Section 10 'The API surface, briefly' must show the signature "
        "starting with 'dispatch(prompt, ...)' verbatim — agents "
        "literally read that line to learn the contract."
    )


def test_quickstart_documents_review_signature() -> None:
    """W13 Wed-Thu: review() is a Tier-1 SDK function; signature required."""
    text = _quickstart_text()
    assert "review(document_path" in text, (
        "AGENT_QUICKSTART.md missing the review() signature.  "
        "Section 10 must show 'review(document_path, ...)' verbatim."
    )


def test_quickstart_documents_capabilities() -> None:
    """W13 Wed-Thu: capabilities() is the orientation entry point."""
    text = _quickstart_text()
    assert "capabilities()" in text, (
        "AGENT_QUICKSTART.md missing capabilities().  This is the "
        "primary tool an agent uses to learn what's installed — must "
        "be documented."
    )


def test_quickstart_documents_audit_show() -> None:
    """W13-AUDIT-JSONL: the audit ledger is opt-in-readable; tell agents."""
    text = _quickstart_text()
    assert "harness audit" in text, (
        "AGENT_QUICKSTART.md missing the `harness audit` CLI surface.  "
        "Every dispatch goes through the audit ledger; agents need to "
        "know it exists + how to inspect it."
    )


def test_quickstart_documents_today_command() -> None:
    """`harness today` is the W8-STATUS-HUMAN orientation surface."""
    text = _quickstart_text()
    assert "harness today" in text, (
        "AGENT_QUICKSTART.md missing `harness today`.  This is the "
        "one-command orientation surface; agents must know it."
    )


def test_all_documented_names_actually_exist_in_all() -> None:
    """The NAMES_DOCUMENTED_BY_REFERENCE allowlist must not gain dead
    entries — every name in it must still be in ``harness.__all__``.
    """
    public = set(_public_sdk_names())
    stale = NAMES_DOCUMENTED_BY_REFERENCE - public
    assert not stale, (
        f"NAMES_DOCUMENTED_BY_REFERENCE has stale entries no longer in "
        f"harness.__all__: {stale}.  Either re-add them to __all__ or "
        f"drop them from the allowlist."
    )
