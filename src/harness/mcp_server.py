"""W14-NATIVE-CC-MCP: expose the harness's cross-vendor verbs as MCP tools.

Lets any MCP client (a Claude Code session, etc.) call cross-vendor
verification natively — ``cross_vendor_audit`` and ``cross_vendor_panel`` —
instead of remembering the ``python -m harness ask`` CLI.  This is the
structural form of the project invariant "cross-vendor work routes THROUGH
the harness" (CLAUDE.md / [feedback_native_features_wire_to_harness]): the
harness becomes a tool surface natives see by default, rather than a CLI a
future session must remember to shell out to.

Design
======
The tool *functions* (:func:`cross_vendor_audit`, :func:`cross_vendor_panel`)
are plain, importable, and reuse :func:`harness.ask.run_audit` /
:func:`harness.ask.run_panel` — so they are unit-testable WITHOUT the MCP SDK
and without real engine calls (tests monkeypatch the dispatch layer).  The MCP
transport wiring lives in :func:`build_server` / :func:`main`, which
lazy-import the ``mcp`` SDK — so ``import harness.mcp_server`` succeeds even
where ``mcp`` is not installed (the SDK is only needed to RUN the server).
"""
from __future__ import annotations

from typing import Any

from harness import ask  # run_audit / run_panel / DEFAULT_ENGINES live here


def _resolve_producer(producer_engine: str = "") -> str:
    """Pick the producer engine for an audit.

    Explicit override wins; otherwise use the health-aware recommender's
    ``default`` pick; fall back to ``mimo-via-claude`` if the recommender is
    unavailable.  No network — the recommender reads a local probe ledger.
    """
    if producer_engine:
        return producer_engine
    try:
        from harness.engines.routing_recommend import recommend_healthy
        rec = recommend_healthy("default")
        if rec and rec.engine:
            return rec.engine
    except Exception:
        pass
    return "mimo-via-claude"


def cross_vendor_audit(
    question: str,
    producer_engine: str = "",
    num_auditors: int = 1,
) -> dict[str, Any]:
    """Cross-vendor fact-check / ship-audit of ``question``.

    Runs a producer answer + a DIFFERENT-vendor auditor through the harness
    (:func:`harness.ask.run_audit`) and returns the verdict
    (PASS / PARTIAL / FAIL / UNKNOWN) plus the auditor's corrections + misses.
    Never answer a cross-vendor question from a single model — that is the
    whole point of routing through the harness.

    Args:
        question: The claim, question, or change-summary to verify.
        producer_engine: Optional explicit producer; default = recommender pick.
        num_auditors: Number of distinct-vendor auditors (default 1; >1 = quorum).
    """
    producer = _resolve_producer(producer_engine)
    outcome = ask.run_audit(
        question, producer_engine=producer, num_auditors=num_auditors,
    )
    verdict = outcome.verdict or {}
    total_cost = float(outcome.producer.cost_usd or 0.0) if outcome.producer else 0.0
    for auditor in outcome.auditors:
        total_cost += float(auditor.cost_usd or 0.0)
    return {
        "verdict": (verdict.get("verdict") or "UNKNOWN")
        if outcome.verdict else "UNKNOWN",
        "summary": verdict.get("summary", ""),
        "corrections": verdict.get("corrections", ""),
        "missed": verdict.get("missed", ""),
        "producer_engine": producer,
        "producer_ok": bool(outcome.producer.ok) if outcome.producer else False,
        "producer_answer": outcome.producer.text if outcome.producer else "",
        "auditor_engines": list(outcome.auditor_engines),
        "audited": bool(outcome.auditors),
        "total_cost_usd": round(total_cost, 6),
    }


def cross_vendor_panel(question: str) -> dict[str, Any]:
    """Fire the cross-vendor panel (3 engines in parallel) for ``question``.

    Returns each engine's answer + cost via :func:`harness.ask.run_panel`.
    Use for design crossroads where vendor diversity matters.
    """
    results = ask.run_panel(question)
    return {
        "engines": [
            {
                "engine": r.engine,
                "ok": bool(r.ok),
                "answer": r.text if r.ok else "",
                "error": r.error if not r.ok else "",
                "cost_usd": round(float(r.cost_usd or 0.0), 6),
                "elapsed_s": round(float(r.elapsed_s or 0.0), 2),
            }
            for r in results
        ],
        "total_cost_usd": round(
            sum(float(r.cost_usd or 0.0) for r in results), 6,
        ),
    }


def build_server():
    """Construct the FastMCP server (lazy-imports the ``mcp`` SDK).

    Raises a clear RuntimeError if ``mcp`` is not installed — the SDK is only
    needed to RUN the server, not to import this module or test its tools.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without SDK
        raise RuntimeError(
            "The 'mcp' SDK is required to run the harness MCP server. "
            "Install it with:  pip install mcp   (or  pip install -e '.[mcp]')."
        ) from exc
    server = FastMCP("xaxiu-harness")
    server.tool()(cross_vendor_audit)
    server.tool()(cross_vendor_panel)
    return server


def main() -> None:
    """Entry point: run the cross-vendor MCP server over stdio."""
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
