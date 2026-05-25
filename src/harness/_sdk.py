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
        Idempotent (cached on the instance after first call).

        W11-PYTHON-SDK-API-IMPL 2026-05-24: routes through
        ``harness.retrieve(dispatch_id, scope='full')`` which reads
        from the dispatch cache that ``W11-CONTEXT-FRUGAL-RETURN-LAZY``
        populates on every successful dispatch.
        """
        # Fast path: text was already loaded (return_mode='full' callers)
        if self.text is not None:
            return self.text
        if not self.dispatch_id:
            raise ResultNotFoundError(
                "DispatchResult.full(): no dispatch_id — cannot lazy-fetch."
            )
        # Lazy import to keep the dataclass module import cheap.
        from harness import retrieve as _retrieve
        body = _retrieve(self.dispatch_id, scope="full")
        # Cache on instance — frozen=False dataclass so direct assign works
        object.__setattr__(self, "text", body)
        return body


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
    # W11-PYTHON-SDK-API-IMPL 2026-05-24: real impl wired to
    # dispatcher.dispatch_packet().  The SDK provides three forms of
    # context preservation on top of the dispatcher:
    #   1. prompt-as-text (write to tempfile so the agent doesn't
    #      have to manually create packets)
    #   2. engine-as-list (first is forced; dispatcher handles fallback)
    #   3. return_mode = summary/full/ref to control text vs context cost
    import os as _os
    import tempfile as _tempfile
    from pathlib import Path as _Path

    # Resolve engine
    force_engine: str | None
    if isinstance(engine, list) and engine:
        force_engine = engine[0]
    elif isinstance(engine, str):
        force_engine = engine
    else:
        force_engine = None

    # Resolve return_mode (with_full_text shortcut overrides)
    if with_full_text:
        return_mode = "full"
    if return_mode not in ("summary", "full", "ref"):
        raise HarnessSDKError(
            f"invalid return_mode {return_mode!r}; "
            f"allowed: 'summary', 'full', 'ref'"
        )

    # Resolve packet_path: if prompt is an existing file path, use it
    # directly; otherwise write to a tempfile.  Tempfile retention:
    # we deliberately do NOT delete on close so the cache + dispatcher
    # can read it asynchronously.  The OS will reap from /tmp.
    packet_path: str
    cleanup_path: _Path | None = None
    try:
        candidate = _Path(prompt)
        if candidate.is_file():
            packet_path = str(candidate)
        else:
            raise ValueError("not a path; fall through to tempfile branch")
    except (OSError, ValueError):
        tmpdir = _tempfile.mkdtemp(prefix="harness_sdk_dispatch_")
        cleanup_path = _Path(tmpdir) / "packet.md"
        cleanup_path.write_text(prompt, encoding="utf-8")
        packet_path = str(cleanup_path)

    # Project resolution: prefer .harness/config.json's project_name,
    # else "default".  Project name must match PROJECT_NAME_REGEX.
    project = "default"
    config_path = _Path.cwd() / ".harness" / "config.json"
    if config_path.exists():
        try:
            import json as _json
            cfg = _json.loads(config_path.read_text(encoding="utf-8"))
            cand = cfg.get("project_name") or cfg.get("project")
            if cand and isinstance(cand, str):
                project = cand
        except (OSError, ValueError):
            pass

    # W11-PYTHON-SDK-API-IMPL E2E-test follow-up: auto-bootstrap the
    # adapter file if missing.  Caught by the first real SDK call —
    # dispatcher requires adapters/<project>/harness-adapter.yaml but
    # an agent freshly cloning the repo + calling harness.dispatch()
    # had no such file.  Now we lazily materialize it from the basic
    # template.  Safe: never overwrites an existing adapter.
    _ensure_default_adapter(project)

    # Cache opt-out: dispatcher reads HARNESS_DISPATCH_CACHE_BYPASS
    cache_env_snapshot = _os.environ.get("HARNESS_DISPATCH_CACHE_BYPASS")
    if no_cache:
        _os.environ["HARNESS_DISPATCH_CACHE_BYPASS"] = "1"

    # W13-AUDIT-JSONL 2026-05-24: capture elapsed for audit ledger so
    # every dispatch lands one append-only redacted row.  Wrapping the
    # dispatch call in a time.monotonic() pair lets us record both
    # successful and failed paths uniformly.
    import time as _time
    _audit_start_mono = _time.monotonic()
    _dispatch_exc: BaseException | None = None
    result = None
    try:
        # Re-import dispatch_packet at call time so test monkeypatches
        # of "harness.engines.dispatcher.dispatch_packet" take effect.
        from harness.engines import dispatcher as _dispatcher
        try:
            result = _dispatcher.dispatch_packet(
                project=project,
                packet_path=packet_path,
                force_engine=force_engine,
            )
        except BaseException as _e:  # noqa: BLE001
            _dispatch_exc = _e
            raise
    finally:
        if no_cache:
            if cache_env_snapshot is None:
                _os.environ.pop("HARNESS_DISPATCH_CACHE_BYPASS", None)
            else:
                _os.environ["HARNESS_DISPATCH_CACHE_BYPASS"] = cache_env_snapshot

        # W13-AUDIT-JSONL: best-effort audit append.  NEVER raises;
        # NEVER blocks the dispatch return / re-raise path.
        try:
            from harness.audit_jsonl import (
                append_dispatch_event as _audit_append,
            )
            _audit_elapsed_ms = int(
                (_time.monotonic() - _audit_start_mono) * 1000,
            )
            if result is not None:
                _audit_engine = getattr(result, "engine_used", "") \
                    or force_engine or "unknown"
                _audit_success = bool(getattr(result, "success", False))
                _audit_error = getattr(result, "error", None) \
                    or getattr(result, "error_excerpt", None)
                _audit_tokens_in = int(
                    getattr(result, "tokens_in", 0) or 0,
                )
                _audit_tokens_out = int(
                    getattr(result, "tokens_out", 0) or 0,
                )
                _audit_cost = float(
                    getattr(result, "cost_usd", 0.0) or 0.0,
                )
                _audit_dispatch_id = getattr(result, "dispatch_id", None)
                _audit_response = getattr(result, "text", None)
                _audit_retry = int(
                    getattr(result, "retry_count", 0) or 0,
                )
            else:
                # Dispatcher itself raised; record what we know.
                _audit_engine = force_engine or "unknown"
                _audit_success = False
                _audit_error = (
                    f"dispatcher_exception: "
                    f"{type(_dispatch_exc).__name__}: {_dispatch_exc}"
                    if _dispatch_exc is not None else "dispatcher_unknown_error"
                )
                _audit_tokens_in = 0
                _audit_tokens_out = 0
                _audit_cost = 0.0
                _audit_dispatch_id = None
                _audit_response = None
                _audit_retry = 0
            _audit_append(
                engine=_audit_engine,
                model=_audit_engine,
                dispatch_id=_audit_dispatch_id,
                success=_audit_success,
                error=_audit_error,
                tokens_in=_audit_tokens_in,
                tokens_out=_audit_tokens_out,
                cost_usd=_audit_cost,
                elapsed_ms=_audit_elapsed_ms,
                retry_count=_audit_retry,
                lens_set=None,  # FUTURE W13-AUTO-LENS: wire when impl lands
                max_tokens_used=None,  # FUTURE W13-AUTO-MAX-TOKENS
                prompt=prompt if isinstance(prompt, str) else None,
                response=_audit_response,
            )
        except Exception:
            pass  # Audit is best-effort; NEVER block the dispatch return path.

    # Convert the dispatcher's DispatchResult (which has a different
    # field set: `error` instead of `error_excerpt`, no `.full()` method)
    # to the SDK's DispatchResult contract.  The agent receives the
    # SDK type with the lazy fetch + context-frugal defaults.
    sdk_result = _to_sdk_result(result, return_mode=return_mode)
    return sdk_result


def _ensure_default_adapter(project: str) -> None:
    """Materialize ``adapters/<project>/harness-adapter.yaml`` from the
    basic template when missing.

    Why: ``dispatch_packet`` loads a per-project adapter YAML.  An
    agent cloning the harness repo and calling ``harness.dispatch()``
    out of the box had no such file for project='default' and saw
    ``adapter_load_failed`` from the very first call.  This auto-
    bootstrap turns "first call works" into the load-bearing UX
    promise — caught by the W11-PYTHON-SDK-API-IMPL E2E test
    (2026-05-24).

    Never overwrites an existing adapter; safe to call repeatedly.
    """
    from pathlib import Path as _Path
    from harness._constants import _REPO_ROOT

    adapter_dir = _REPO_ROOT / "adapters" / project
    adapter_path = adapter_dir / "harness-adapter.yaml"
    if adapter_path.exists():
        return  # already in place; nothing to do

    template = _REPO_ROOT / "adapters" / "templates" / "basic.yaml"
    if not template.exists():
        # No template to copy from; let the dispatcher surface its
        # own adapter_load_failed error rather than masking with a
        # surprising side-effect.
        return

    try:
        adapter_dir.mkdir(parents=True, exist_ok=True)
        # Replace the template's `name: demo` with the actual project
        # name so downstream tooling (status tracker, observer) reports
        # the right adapter identity.
        text = template.read_text(encoding="utf-8")
        text = text.replace("name: demo", f"name: {project}", 1)
        adapter_path.write_text(text, encoding="utf-8")
    except OSError:
        # Best-effort: if we can't write, let the dispatcher fail
        # with its normal error path.
        pass


def _to_sdk_result(dispatcher_result, return_mode: ReturnMode) -> DispatchResult:
    """Map the dispatcher's DispatchResult onto the SDK's contract.

    The two dataclasses differ in field names (``error`` vs
    ``error_excerpt``) and the SDK type has a ``.full()`` method the
    dispatcher's does not.  This boundary conversion lets the agent
    interact with the cleaner SDK shape without leaking dispatcher
    internals.
    """
    # Extract error_excerpt: prefer the dispatcher's error_excerpt
    # (if present per W11-CONTEXT-FRUGAL-RETURN-SCHEMA), else fall back
    # to the older `error` field.
    err_excerpt = getattr(dispatcher_result, "error_excerpt", None)
    if not err_excerpt:
        err_val = getattr(dispatcher_result, "error", "") or ""
        err_excerpt = err_val if err_val else None

    text_val: str | None = getattr(dispatcher_result, "text", None)
    summary_val = getattr(dispatcher_result, "summary", "") or ""
    truncated = getattr(dispatcher_result, "truncated", True)
    content_ref = getattr(dispatcher_result, "content_ref", None)

    if return_mode == "summary":
        # Strip text; agent can retrieve() later via dispatch_id.
        text_val = None
        truncated = True
    elif return_mode == "ref":
        text_val = None
        summary_val = ""
        truncated = True
    # else "full": keep dispatcher's text + summary

    return DispatchResult(
        success=getattr(dispatcher_result, "success", False),
        engine_used=getattr(dispatcher_result, "engine_used", ""),
        dispatch_id=getattr(dispatcher_result, "dispatch_id", ""),
        summary=summary_val,
        truncated=truncated,
        error_excerpt=err_excerpt,
        content_ref=content_ref,
        text=text_val,
        tokens_in=getattr(dispatcher_result, "tokens_in", 0),
        tokens_out=getattr(dispatcher_result, "tokens_out", 0),
        cost_usd=getattr(dispatcher_result, "cost_usd", 0.0),
        fallback_chain=list(getattr(dispatcher_result, "fallback_chain", [])),
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
