"""W11-PYTHON-SDK-API-STUBS: agent-facing Python SDK contract.

This module defines the public stable API that agentic coding agents
import via `from harness import dispatch, retrieve, budget_status`.
The bodies raise NotImplementedError; the real implementations land in
W11-PYTHON-SDK-API-IMPL (Wave 11-D) after the W11-B context-frugal
return + cache + retrieve rows stabilize.

The contract — function signatures, DispatchResult dataclass, exception
types — is FROZEN as of this row.  Downstream rows MUST target this
contract; breaking it requires a wave-level decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# Return-mode literal type (consumers can use this in their own type hints)
ReturnMode = Literal["summary", "full", "ref"]
RetrieveScope = Literal["summary", "full", "chunks"]


@dataclass
class DispatchResult:
    """Result of a single `harness.dispatch()` call.

    Default fields are CONTEXT-FRUGAL — `.summary` is short (~200-300
    tokens of head+tail extraction from the engine response), and the
    full text is NOT loaded into the caller's context unless they
    explicitly call `.full()`.

    Per W11-CONTEXT-FRUGAL-RETURN-LAZY contract:
      - `.summary` always populated (≤300 chars typical)
      - `.text` populated only when `dispatch(return_mode='full')` was used
      - `.error_excerpt` populated on engine failure (top-level signal
        the agent can check without reading the full body)
      - `.content_ref` always populated; pass to `.full()` or
        `harness.retrieve()` for the full text on demand
    """
    success: bool
    engine_used: str
    dispatch_id: str
    summary: str = ""
    truncated: bool = True
    error_excerpt: str | None = None
    content_ref: str | None = None
    text: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    fallback_chain: list[str] = field(default_factory=list)

    def full(self) -> str:
        """Lazy-fetch the full response text from the dispatch store.

        Burns context proportional to response size — the agent calls
        this only when the `.summary` indicates more detail is needed.
        Idempotent (cached after first call).

        Implemented in W11-PYTHON-SDK-API-IMPL (Wave 11-D).
        """
        raise NotImplementedError(
            "DispatchResult.full() is pending W11-PYTHON-SDK-API-IMPL "
            "(Wave 11-D).  Until then, use the legacy "
            "harness.engines.dispatcher.dispatch_packet() which returns "
            "full text by default."
        )


class HarnessSDKError(Exception):
    """Base exception for SDK calls."""


class ResultNotFoundError(HarnessSDKError):
    """Raised by retrieve() when dispatch_id has no stored result."""


class ResultCorruptedError(HarnessSDKError):
    """Raised by retrieve() when the on-disk result is malformed."""


# -- Public API stubs (W11-PYTHON-SDK-API-IMPL fills these in) ------------


def dispatch(prompt: str,
             engine: str | list[str] | None = None,
             *,
             return_mode: ReturnMode = "summary",
             timeout_sec: float = 420.0,
             with_full_text: bool = False,
             no_cache: bool = False) -> DispatchResult:
    """Send *prompt* to the harness engine pool; return a DispatchResult.

    W11-PYTHON-SDK-API contract (STUB; real impl in Wave 11-D):

    Args:
        prompt: The packet text or path-to-packet to dispatch.
        engine: Specific backend (kimi/deepseek/mimo/anthropic/gemini),
            an ordered fallback list, or None for adapter-driven routing.
        return_mode: "summary" (default; ≤300-token head+tail extract)
            | "full" (legacy; loads full text into result.text)
            | "ref" (metadata-only; even summary not computed)
        timeout_sec: Per-engine timeout.  Falls through to next in
            fallback chain on timeout.
        with_full_text: Shortcut for return_mode="full".  Preserved for
            HARNESS_DISPATCH_FULL_BY_DEFAULT migration period.
        no_cache: Bypass the dispatch cache (W11-DISPATCH-CACHE).
            Default False = use cache if hit.

    Returns:
        DispatchResult — default shape preserves agent context window
        (see DispatchResult docstring).

    Raises:
        HarnessSDKError on engine pool exhaustion or invalid input.
    """
    raise NotImplementedError(
        "harness.dispatch() is pending W11-PYTHON-SDK-API-IMPL "
        "(Wave 11-D).  Until then, use the CLI verb `harness dispatch` "
        "or import harness.engines.dispatcher.dispatch_packet() directly."
    )


def retrieve(dispatch_id: str,
             scope: RetrieveScope = "summary",
             *,
             chunk_size_tokens: int = 2000,
             project_root: str | None = None) -> str | list[str]:
    """Fetch a stored dispatch result on-demand.

    W11-RETRIEVE-API 2026-05-25: reads from the dispatch cache that
    W11-CONTEXT-FRUGAL-RETURN-LAZY populates on every successful
    dispatch.  Cache lives at <project_root>/.harness/dispatched/
    <dispatch_id>.json.

    Args:
        dispatch_id: The id from a prior DispatchResult.dispatch_id.
        scope: "summary" (≤300-char extract; cheap), "full" (entire
            text; burns context proportional to size), or "chunks"
            (list of chunk_size_tokens-token strings for paginated read).
        chunk_size_tokens: Only used with scope="chunks".  Default
            2000 tokens (~8000 chars assuming 4 chars/token).
        project_root: Override the project root (defaults to cwd).

    Returns:
        - scope="summary" or "full" -> str
        - scope="chunks" -> list[str]

    Raises:
        ResultNotFoundError: dispatch_id not in cache
        ResultCorruptedError: stored payload is malformed / missing expected fields
        ValueError: invalid scope
    """
    if scope not in ("summary", "full", "chunks"):
        raise ValueError(
            f"unknown scope {scope!r}; allowed: 'summary', 'full', 'chunks'"
        )
    from pathlib import Path
    from harness.engines import dispatch_cache as _dc
    pr = Path(project_root) if project_root else None
    payload = _dc.lookup_by_id(dispatch_id, project_root=pr,
                                ttl_sec=0)  # ttl=0 = no expiry on retrieve
    if payload is None:
        raise ResultNotFoundError(
            f"no cached dispatch for id={dispatch_id!r}; either it "
            f"never ran, the cache was cleared, or you're looking in "
            f"the wrong project_root (default cwd)."
        )
    if not isinstance(payload, dict):
        raise ResultCorruptedError(
            f"cached payload for {dispatch_id!r} is not a dict: "
            f"{type(payload).__name__}"
        )
    # Sentinel distinguishes "key absent" (corruption) from
    # "key present with empty value" (zero-length response).
    _MISSING = object()
    full_text = payload.get("full_text", _MISSING)
    summary_text = payload.get("summary", _MISSING)
    if scope == "summary":
        if summary_text is _MISSING:
            raise ResultCorruptedError(
                f"cached payload for {dispatch_id!r} missing 'summary' field"
            )
        return summary_text
    if scope == "full":
        if full_text is _MISSING:
            raise ResultCorruptedError(
                f"cached payload for {dispatch_id!r} missing 'full_text' field"
            )
        return full_text
    # scope == "chunks"
    if full_text is _MISSING:
        raise ResultCorruptedError(
            f"cached payload for {dispatch_id!r} missing 'full_text' field"
        )
    # Approximate: 1 token ≈ 4 chars (English text).  Minimum 1 char so
    # tests + tiny dispatches don't fall into a single-floor lump.
    chunk_size_chars = max(1, chunk_size_tokens * 4)
    chunks: list[str] = []
    pos = 0
    while pos < len(full_text):
        chunks.append(full_text[pos:pos + chunk_size_chars])
        pos += chunk_size_chars
    return chunks


def budget_status(*, since_hours: float | None = None,
                  ledger_path=None) -> dict:
    """Return the current session's offload + cost telemetry.

    W11-AGENT-TELEMETRY 2026-05-25 implementation.

    Returns a dict:
        session_tokens_total: int (input + output across all engines)
        session_cost_total: float USD
        offload_ratio: float in [0, 1] — subscription / (subscription+paid)
        remaining_budget_usd: float — COST_MAX_PER_SESSION minus spent
        dispatches_fired: int
        engines_used: dict[engine_name, dispatch_count]
        avg_cost_per_token: float (0.0 when no tokens recorded)
        cost_max_per_session_usd: float (from env or default 5.0)
        window_hours: float | None — None = entire ledger

    Args:
        since_hours: Window in hours; None = entire ledger.
        ledger_path: Override the ledger path (for tests).

    Cheap to call; payload stays <2KB so agents can poll between
    dispatches without context cost.
    """
    import os as _os
    from datetime import datetime, timedelta, timezone
    from harness import budget as _budget

    # Subscription engines have zero marginal cost
    SUBSCRIPTION_ENGINES = frozenset({
        "kimi", "kimi-api", "mimo", "mimo-pro",
        "swarm/kimi", "swarm/kimi-api", "swarm/mimo",
        "mimo-sub", "mimo-pro-sub",
    })

    since_iso = None
    if since_hours is not None and since_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        since_iso = cutoff.isoformat()

    summary = _budget.summary(ledger_path=ledger_path, since_iso=since_iso)
    total_in = sum(s["total_input_tokens"] for s in summary.values())
    total_out = sum(s["total_output_tokens"] for s in summary.values())
    total_tokens = int(total_in + total_out)
    total_cost = round(sum(s["total_cost_usd"] for s in summary.values()), 6)
    dispatches = int(sum(s["dispatches"] for s in summary.values()))

    engines_used = {engine: int(s["dispatches"])
                    for engine, s in summary.items()}

    # Offload ratio: subscription tokens / (subscription + paid tokens)
    sub_tokens = 0
    paid_tokens = 0
    for engine, s in summary.items():
        eng_total = int(s["total_input_tokens"] + s["total_output_tokens"])
        if engine in SUBSCRIPTION_ENGINES:
            sub_tokens += eng_total
        else:
            paid_tokens += eng_total
    if sub_tokens + paid_tokens > 0:
        offload_ratio = round(sub_tokens / (sub_tokens + paid_tokens), 4)
    else:
        offload_ratio = 0.0

    try:
        cost_max = float(_os.environ.get("COST_MAX_PER_SESSION", "5.00"))
    except ValueError:
        cost_max = 5.00
    remaining = round(cost_max - total_cost, 6)

    avg_per_token = round(total_cost / total_tokens, 8) if total_tokens else 0.0

    return {
        "session_tokens_total": total_tokens,
        "session_cost_total": total_cost,
        "offload_ratio": offload_ratio,
        "remaining_budget_usd": remaining,
        "dispatches_fired": dispatches,
        "engines_used": engines_used,
        "avg_cost_per_token": avg_per_token,
        "cost_max_per_session_usd": cost_max,
        "window_hours": since_hours,
    }
