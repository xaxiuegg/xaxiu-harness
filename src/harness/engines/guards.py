"""Engine-specific guards — detection + enrichment layer for engine responses.

This module implements the forensic-signal recovery layer promised by
ACCEPT-3 in ``spec/ACCEPTED_LIMITATIONS.md``.  It wraps raw engine output
to surface engine-specific failure modes **before** the broad
``except Exception`` in ``concrete.dispatch`` buries them as the generic
``"internal"`` label.

Detection rules
---------------
1. **DeepSeek v4-flash packet trap** — If a ``-flash`` model returns text
   that looks like a JSON tool-call (starts with ``{``, contains
   ``"name":`` and ``"arguments":``), the response is re-labelled
   ``error="packet_trap"`` so the dispatcher can fall back.
   (v1.2 HIGH-7, operator memory ``feedback_deepseek_v4_no_tools_packet.md``)

2. **Kimi empty response / timeout pattern** — Kimi occasionally returns
   an empty body or a bare ``<?xml ...`` preamble on multi-domain bundles.
   Re-labelled ``error="kimi_empty_or_xml"``.
   (operator memory ``feedback_engine_anchor_accuracy.md``)

3. **Anthropic refusal pattern** — Detects policy refusals in the first
   500 characters (e.g. "I cannot...", "I can't...").
   Re-labelled ``error="anthropic_refusal"``.

4. **Anchor fuzzy check** — Post-validates that expected anchor strings
   appear in the generated text, allowing for smart-quote normalisation
   and whitespace collapse.
   (operator memory ``feedback_engine_anchor_accuracy.md``)

Security contract
-----------------
- This module is **pure**: no IO, no global mutable state, no logging,
  no network, no ``eval``/``exec``.
- Sensitive data (``response.text``, ``packet_content``, ``anchors``) are
  **never** written to stdout, stderr, or disk.
- All regular expressions are compiled once at import time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from harness.engines.base import EngineResponse


# ---------------------------------------------------------------------------
# Module-level compiled regexes
# ---------------------------------------------------------------------------

_RE_KIMI_XML = re.compile(r"^\s*<\?xml")
_RE_ANTHROPIC_REFUSAL = re.compile(r"(?i)i (cannot|can't|won't|am unable)")
_RE_WHITESPACE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Anchor fuzzy-check helpers
# ---------------------------------------------------------------------------

# Map common smart quotation marks to straight ASCII equivalents.
_SMART_QUOTE_TABLE = str.maketrans({
    "\u2018": "'",   # left single quotation mark
    "\u2019": "'",   # right single quotation mark
    "\u201c": '"',   # left double quotation mark
    "\u201d": '"',   # right double quotation mark
    "\u00ab": '"',   # left-pointing double angle quotation mark
    "\u00bb": '"',   # right-pointing double angle quotation mark
    "\u2039": "'",   # single left-pointing angle quotation mark
    "\u203a": "'",   # single right-pointing angle quotation mark
})


def _normalize_text(text: str) -> str:
    """Return a canonical form of *text* for fuzzy comparison.

    Steps:
    1. Replace smart quotes with straight ASCII quotes.
    2. Collapse all whitespace sequences to a single space.
    3. Strip leading / trailing whitespace.
    """
    text = text.translate(_SMART_QUOTE_TABLE)
    text = _RE_WHITESPACE.sub(" ", text)
    return text.strip()


@dataclass(frozen=True)
class AnchorReport:
    """Result of an anchor-fuzzy check against an engine response.

    Attributes:
        total: Total number of anchors checked.
        byte_exact: Number of anchors found via byte-exact substring match.
        fuzzy_match: Number of anchors found only after normalisation.
        missing: Number of anchors not found at all.
        risk: Aggregated risk level — ``LOW`` when every anchor matches
            byte-exactly, ``MED`` when at least one fuzzy match exists
            with zero missing, and ``HIGH`` when any anchor is missing.
    """

    total: int
    byte_exact: int
    fuzzy_match: int
    missing: int
    risk: Literal["LOW", "MED", "HIGH"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_response(
    *,
    backend: str,
    model: str | None,
    packet_content: str,
    response: EngineResponse,
) -> EngineResponse:
    """Inspect *response* and return a possibly re-labelled copy.

    This function never raises and never performs IO.  If none of the
    engine-specific heuristics match, the original *response* is returned
    unchanged.

    Args:
        backend: Canonical backend name (e.g. ``"deepseek"``).
        model: Model identifier, or ``None`` if unknown.
        packet_content: The original dispatch packet text (unused by the
            current rule set, but part of the stable API contract).
        response: Raw :class:`EngineResponse` from the engine.

    Returns:
        An :class:`EngineResponse` with a more-specific ``error`` field
        when a known failure mode is detected.
    """
    # Rule 0 — MockEngine is deterministic; never re-label.
    if backend == "mock":
        return response

    # Rule 1 — DeepSeek v4-flash packet trap
    if (
        backend == "deepseek"
        and model is not None
        and model.endswith("-flash")
        and response.text.startswith("{")
        and '"name":' in response.text
        and '"arguments":' in response.text
    ):
        return EngineResponse(
            success=False,
            text=response.text,
            latency_ms=response.latency_ms,
            error="packet_trap",
        )

    # Rule 2 — Kimi empty response / timeout pattern
    # L-1 fix: force success=False so dispatcher falls back instead of returning empty.
    if backend == "kimi" and (
        response.text.strip() == "" or _RE_KIMI_XML.match(response.text)
    ):
        return EngineResponse(
            success=False,
            text=response.text,
            latency_ms=response.latency_ms,
            error="kimi_empty_or_xml",
        )

    # Rule 3 — Anthropic refusal pattern
    # L-1 fix: force success=False so a refusal triggers fallback.
    if (
        backend == "anthropic"
        and _RE_ANTHROPIC_REFUSAL.search(response.text[:500])
    ):
        return EngineResponse(
            success=False,
            text=response.text,
            latency_ms=response.latency_ms,
            error="anthropic_refusal",
        )

    # Rule 4 — MiMo silent-empty (W4-J 2026-05-22)
    # The W4-G multi-agent campaign caught MiMo v2.5-Pro returning
    # success=True text="" on 3/5 dispatches with source-laden packets
    # (~4KB).  Re-label so the dispatcher falls back instead of pretending
    # the empty body is a valid response.  Covers BOTH Pro and Standard
    # variants since the empty-text symptom is identical.
    #
    # Only re-label SUCCESS responses — an already-failed response (e.g.
    # HTTP 500 with empty body) keeps its more-specific original error.
    if backend == "mimo" and response.success and response.text.strip() == "":
        return EngineResponse(
            success=False,
            text=response.text,
            latency_ms=response.latency_ms,
            error="mimo_empty",
        )

    # Rule 5 — no match
    return response


def should_split_kimi_bundle(packet_content: str) -> bool:
    """Return ``True`` if *packet_content* looks like a multi-domain bundle.

    Heuristic: at least two **distinct** second-level Markdown headers
    (``## ``) and the total UTF-8 encoded size exceeds 8 KiB.
    """
    lines = packet_content.splitlines()
    headings = {
        line[3:].strip()
        for line in lines
        if line.startswith("## ")
    }
    if len(headings) < 2:
        return False
    return len(packet_content.encode("utf-8")) > 8192


def split_multi_domain_packet(packet_content: str) -> list[str]:
    """Split a multi-domain packet into sub-packets.

    Preconditions:
        * ``should_split_kimi_bundle(packet_content)`` is ``True``.

    The document preamble (everything before the first ``## `` header) is
    prepended to each section.  Each section starts at a ``## `` line and
    runs up to (but not including) the next ``## `` line.

    Args:
        packet_content: The full packet text.

    Returns:
        A list of sub-packet strings ready for individual dispatch.
    """
    lines = packet_content.splitlines(keepends=True)

    # Locate the first heading to determine the preamble.
    first_heading_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("## ")),
        None,
    )
    if first_heading_idx is None:
        # Defensive: no headings found — return the whole document.
        return [packet_content]

    preamble = "".join(lines[:first_heading_idx])

    # Collect the start index of every heading line.
    heading_indices = [
        i for i, line in enumerate(lines) if line.startswith("## ")
    ]

    sub_packets: list[str] = []
    for idx, start in enumerate(heading_indices):
        end = (
            heading_indices[idx + 1]
            if idx + 1 < len(heading_indices)
            else len(lines)
        )
        section = "".join(lines[start:end])
        sub_packets.append(preamble + section)

    return sub_packets


def anchor_fuzzy_check(
    response_text: str,
    anchors: list[str],
) -> AnchorReport:
    """Check whether *anchors* appear in *response_text*.

    For each anchor:
    1. **Byte-exact** — ``anchor in response_text``.
    2. **Fuzzy** — after normalising smart quotes and collapsing
       whitespace, check again.
    3. **Missing** — neither exact nor fuzzy match.

    Risk assessment:
    - ``HIGH`` if any anchor is missing.
    - ``MED`` if at least one fuzzy match exists and zero are missing.
    - ``LOW`` if every anchor matches byte-exactly.

    Args:
        response_text: The engine-generated text to inspect.
        anchors: Expected anchor strings (e.g. file paths, signatures).

    Returns:
        An :class:`AnchorReport` summarising the results.
    """
    norm_response = _normalize_text(response_text)

    byte_exact = 0
    fuzzy_match = 0
    missing = 0

    for anchor in anchors:
        if anchor in response_text:
            byte_exact += 1
            continue

        if _normalize_text(anchor) in norm_response:
            fuzzy_match += 1
            continue

        missing += 1

    total = len(anchors)
    if missing > 0:
        risk: Literal["LOW", "MED", "HIGH"] = "HIGH"
    elif fuzzy_match > 0:
        risk = "MED"
    else:
        risk = "LOW"

    return AnchorReport(
        total=total,
        byte_exact=byte_exact,
        fuzzy_match=fuzzy_match,
        missing=missing,
        risk=risk,
    )
