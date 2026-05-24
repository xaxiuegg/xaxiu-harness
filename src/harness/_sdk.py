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
             chunk_size_tokens: int = 2000) -> str | list[str]:
    """Fetch a stored dispatch result on-demand.

    Args:
        dispatch_id: The id from a prior DispatchResult.dispatch_id.
        scope: "summary" (≤300-char extract; cheap), "full" (entire
            text; burns context proportional to size), or "chunks"
            (list of chunk_size_tokens-token strings for paginated read).
        chunk_size_tokens: Only used with scope="chunks".

    Returns:
        - scope="summary" or "full" -> str
        - scope="chunks" -> list[str]

    Raises:
        ResultNotFoundError: id not in dispatch store
        ResultCorruptedError: stored result is malformed
    """
    raise NotImplementedError(
        "harness.retrieve() is pending W11-PYTHON-SDK-API-IMPL + "
        "W11-RETRIEVE-API (Wave 11-D)."
    )


def budget_status() -> dict:
    """Return the current session's offload + cost telemetry.

    Returns a dict with:
        session_tokens_total: int
        session_cost_total: float
        offload_ratio: float in [0, 1] — harness-engine tokens / total
        remaining_budget_usd: float — COST_MAX_PER_SESSION minus spent
        dispatches_fired: int
        engines_used: dict[engine_name, count]
        avg_cost_per_token: float
        cost_max_per_session_usd: float

    Cheap to call; the agent can poll between dispatches without
    significant context cost (the dict is small).  Implementation
    lives behind W11-AGENT-TELEMETRY + W11-PYTHON-SDK-API-IMPL.
    """
    raise NotImplementedError(
        "harness.budget_status() is pending W11-AGENT-TELEMETRY "
        "(Wave 11-C) + W11-PYTHON-SDK-API-IMPL (Wave 11-D)."
    )
