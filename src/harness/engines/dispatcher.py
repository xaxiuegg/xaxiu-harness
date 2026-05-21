"""Auto-fallback orchestrator for xaxiu-harness.

Routes packets to the appropriate backend engine using a priority hierarchy
(LOCK > BURST > routing rules > global priority), executes the dispatch, and
automatically falls back to alternative engines on failure.

Security guarantees
-------------------
* Packet content is NEVER written to logs — only ``packet_path`` is recorded.
* Fallback reasons use audited ``EngineResponse.error`` strings only.
* ``insert_routing_change`` is called whenever LOCK / BURST / priority
  overrides are consulted (v1.2 MED-9).
* ``dispatch_packet`` never raises — all errors are returned as
  ``DispatchResult(success=False, error="...")``.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness._constants import PROJECT_NAME_REGEX, SUPPORTED_BACKENDS
from harness.adapters.loader import load_project_adapter
from harness.adapters.schema import AdapterConfig, RoutingRule
from harness.engines import guards  # M-3 fix: forensic classification on every response
from harness.engines.base import EngineResponse
from harness.engines.concrete import get_engine
from harness.state import db as state_db
from harness.state import files as state_files
from harness.state import jsonl_log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PACKET_BYTES: int = 10 * 1024 * 1024

_PRIORITY_ORDER: dict[str, int] = {"HIGH": 0, "NORMAL": 1, "AVOID": 2}

# "mock" is reachable via ``force_engine="mock"`` but is excluded from the
# auto-fallback chain, LOCK/BURST resolution, and the "no engines remaining"
# exhaustion check.  Centralizing the filter here prevents drift across
# the four loops below that all walk SUPPORTED_BACKENDS.
_NON_PRODUCTION_BACKENDS: frozenset[str] = frozenset({"mock"})


def _production_backends() -> list[str]:
    return [b for b in SUPPORTED_BACKENDS if b not in _NON_PRODUCTION_BACKENDS]

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchResult:
    """Immutable result of a complete dispatch attempt (including fallbacks)."""

    success: bool
    engine_used: str           # final engine that produced (or failed) the response
    fallback_chain: list[str]  # ordered list of engines tried, including the last
    text: str                  # engine response text (empty on total failure)
    error: str | None
    dispatch_id: str           # UUID written to history.db
    tokens_used: int = 0
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _priority_rank(priority: str) -> int:
    """Return sort rank for engine priority (lower = higher precedence)."""
    return _PRIORITY_ORDER.get(priority, 1)


def _now_iso() -> str:
    """Current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _read_packet(path: str) -> str:
    """Read *path* as UTF-8 text, rejecting files larger than ``MAX_PACKET_BYTES``."""
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_PACKET_BYTES:
        raise ValueError(
            f"Packet file {size} bytes exceeds limit {MAX_PACKET_BYTES}"
        )
    return p.read_text(encoding="utf-8")


# PACKET-INJECTION-FILTER (2026-05-21).  Outbound packets should never
# instruct a worker to read environment variables, invoke DPAPI directly,
# or make outbound network requests to arbitrary hosts.  Patterns matched
# here are HEURISTIC — a determined attacker can evade with obfuscation —
# but they catch the obvious "exfiltrate DEEPSEEK_API_KEY via curl"
# templates that would otherwise sneak through an LLM-generated spec.

import re as _re

_INJECTION_PATTERNS: list[tuple[str, "_re.Pattern[str]"]] = [
    # Windows env-var refs inside scripts
    ("env_var_windows", _re.compile(r"\$env:[A-Z_][A-Z0-9_]*", _re.IGNORECASE)),
    ("env_var_pct", _re.compile(r"%[A-Z][A-Z0-9_]+%")),
    # Python env access
    ("env_var_python", _re.compile(r"os\.environ(?:\[[^\]]+\]|\.get\()")),
    # DPAPI exfiltration
    ("dpapi_direct", _re.compile(r"(decrypt_secret|read_secret|list_secrets)\s*\(",
                                  _re.IGNORECASE)),
    # Outbound HTTP primitives
    ("net_invoke", _re.compile(r"Invoke-WebRequest|Invoke-RestMethod", _re.IGNORECASE)),
    ("net_curl", _re.compile(r"\bcurl\s+(?:[-A-Za-z]+\s+)*https?://")),
    ("net_wget", _re.compile(r"\bwget\s+https?://")),
    # Common API-key var names in literal references
    ("api_key_literal", _re.compile(
        r"(KIMI|DEEPSEEK|ANTHROPIC|GEMINI|MOONSHOT|OPENAI)_API_KEY")),
]


def scan_packet_for_injection(text: str) -> list[tuple[str, str]]:
    """Return a list of ``(pattern_name, excerpt)`` for each suspicious match.

    Returns an empty list when no patterns match.  Excerpts are clipped at
    120 chars to avoid leaking the surrounding spec content into logs.
    """
    findings: list[tuple[str, str]] = []
    for name, pat in _INJECTION_PATTERNS:
        m = pat.search(text)
        if m is not None:
            excerpt = text[max(0, m.start() - 20): m.end() + 40][:120]
            findings.append((name, excerpt))
    return findings


def _eligible_engines(
    health: dict[str, state_files.EngineHealth],
    exclude: set[str],
) -> list[tuple[str, str]]:
    """Return ``(name, priority)`` tuples sorted by priority (HIGH first).

    Non-production backends (see ``_NON_PRODUCTION_BACKENDS``) are
    unconditionally filtered out — they are reachable only via
    ``force_engine``.
    """
    eligible: list[tuple[str, str]] = []
    for name in _production_backends():
        if name in exclude:
            continue
        h = health.get(name)
        priority = h.priority if h else "NORMAL"
        eligible.append((name, priority))
    eligible.sort(key=lambda x: _priority_rank(x[1]))
    return eligible


def _resolve_locked_engine(
    health: dict[str, state_files.EngineHealth],
) -> str | None:
    """Return the highest-priority locked engine, or ``None``."""
    locked: list[tuple[str, str]] = []
    for name in _production_backends():
        h = health.get(name)
        if h and h.locked:
            locked.append((name, h.priority))
    if not locked:
        return None
    locked.sort(key=lambda x: _priority_rank(x[1]))
    return locked[0][0]


def _resolve_burst_engine(
    health: dict[str, state_files.EngineHealth],
) -> str | None:
    """Return the highest-priority engine with an active burst, or ``None``."""
    now = _now_iso()
    bursting: list[tuple[str, str]] = []
    for name in _production_backends():
        h = health.get(name)
        if h and h.burst_until and h.burst_until > now:
            bursting.append((name, h.priority))
    if not bursting:
        return None
    bursting.sort(key=lambda x: _priority_rank(x[1]))
    return bursting[0][0]


def _map_error_to_outcome(error: str | None) -> str:
    """Map an ``EngineResponse.error`` to a JSONL-log ``outcome`` value."""
    if error == "timeout":
        return "timeout"
    return "api_error"


def _audit_routing_change(
    action: str,
    engine: str,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    """Best-effort routing-change audit.  Swallows DB errors silently."""
    try:
        state_db.insert_routing_change(
            source="cli",
            action=action,
            engine=engine,
            old_value=old_value,
            new_value=new_value,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------


def _pick_initial_engine(
    adapter: AdapterConfig,
    health: dict[str, state_files.EngineHealth],
    packet_path: str,
    force_engine: str | None,
) -> tuple[str, str | None, dict[str, Any]]:
    """Return ``(engine_name, model, extra_args)`` for the first attempt.

    The selection follows the v1 §9 hierarchy:
    LOCK > BURST > routing rules > global priority > default.
    """
    if force_engine is not None:
        return force_engine, None, {}

    # 1. LOCK
    locked = _resolve_locked_engine(health)
    if locked is not None:
        _audit_routing_change("lock", locked, new_value="selected")
        return locked, None, {}

    # 2. BURST
    burst = _resolve_burst_engine(health)
    if burst is not None:
        _audit_routing_change("burst_start", burst, new_value="selected")
        return burst, None, {}

    # 3. Routing rules (lowest-priority in hierarchy)
    for rule in adapter.routing_rules:
        if fnmatch.fnmatch(packet_path, rule.if_):
            action = rule.then
            backend = action.backend
            model = action.model
            extra = action.extra_args

            if backend == "burst":
                burst_engine = _resolve_burst_engine(health)
                if burst_engine is not None:
                    # M-1 fix: audit BURST consultation reached via rule.
                    _audit_routing_change(
                        "burst_start", burst_engine, new_value="rule-selected"
                    )
                    return burst_engine, model, extra
                # No active burst — fall through to default selection.
                break

            # Priority override: if the rule-selected engine is AVOIDed,
            # jump to the next best eligible engine.
            h = health.get(backend)
            if h is not None and h.priority == "AVOID":
                eligible = _eligible_engines(health, exclude=set())
                if eligible and eligible[0][0] != backend:
                    better = eligible[0][0]
                    _audit_routing_change(
                        "priority_change",
                        backend,
                        old_value="AVOID",
                        new_value=f"skipped to {better}",
                    )
                    return better, model, extra

            return backend, model, extra

    # 4. Default by global priority
    eligible = _eligible_engines(health, exclude=set())
    if eligible:
        # M-1 fix: audit default-priority selection (no routing rule matched).
        _audit_routing_change(
            "priority_change",
            eligible[0][0],
            new_value="default-priority-selected",
        )
        return eligible[0][0], None, {}

    return _production_backends()[0], None, {}


# ---------------------------------------------------------------------------
# Active-dispatch helpers
# ---------------------------------------------------------------------------


def _remove_active_dispatch(dispatch_id: str) -> None:
    """Best-effort removal of a dispatch from active_dispatches."""
    try:
        actives = state_files.read_active_dispatches()
        actives = [a for a in actives if a.dispatch_id != dispatch_id]
        state_files.write_active_dispatches(actives)
    except Exception:
        pass


def _update_active_dispatch_fallback(
    dispatch_id: str,
    next_engine: str,
) -> None:
    """Update ``current_backend``, ``fallback_count``, and ``status`` for a fallback."""
    try:
        actives = state_files.read_active_dispatches()
        updated: list[state_files.ActiveDispatch] = []
        for a in actives:
            if a.dispatch_id == dispatch_id:
                data = a.model_dump(mode="json")
                data["current_backend"] = next_engine
                data["fallback_count"] = data.get("fallback_count", 0) + 1
                data["status"] = "fallback"
                updated.append(state_files.ActiveDispatch.model_validate(data))
            else:
                updated.append(a)
        state_files.write_active_dispatches(updated)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def dispatch_packet(
    *,
    project: str,
    packet_path: str,
    force_engine: str | None = None,
    force_model: str | None = None,
    wave_id: str | None = None,
) -> DispatchResult:
    """Route *packet_path* to an engine, with automatic fallback on failure.

    Args:
        project: Project name (validated against ``PROJECT_NAME_REGEX``).
        packet_path: Filesystem path to the dispatch packet.
        force_engine: Bypass routing rules and use this engine (must be in
            ``SUPPORTED_BACKENDS``).  LOCK refusal is still respected.
        force_model: Override the model selected by routing rules.
        wave_id: Optional STATUS.csv row id; when supplied, the dispatcher
            invokes ``harness.status.hooks.on_dispatch_start`` before the
            engine call and ``on_dispatch_complete`` after it.  When
            ``None``, STATUS tracking is skipped entirely (keeps the file
            curated for operator-defined waves only).  Hook failures never
            propagate — STATUS bookkeeping must not break dispatch.

    Returns:
        A ``DispatchResult`` describing the outcome.  This function never
        raises; all errors are surfaced via ``DispatchResult.success=False``.
    """
    # ---- 1. Validate project name -----------------------------------------
    if not re.fullmatch(PROJECT_NAME_REGEX, project):
        return DispatchResult(
            success=False,
            engine_used="",
            fallback_chain=[],
            text="",
            error="invalid_project_name",
            dispatch_id="",
        )

    # ---- 2. Validate force_engine -----------------------------------------
    if force_engine is not None and force_engine not in SUPPORTED_BACKENDS:
        return DispatchResult(
            success=False,
            engine_used="",
            fallback_chain=[],
            text="",
            error="unsupported_force_engine",
            dispatch_id="",
        )

    # ---- 3. Load adapter ----------------------------------------------------
    try:
        adapter = load_project_adapter(project)
    except (ValueError, FileNotFoundError) as exc:
        return DispatchResult(
            success=False,
            engine_used="",
            fallback_chain=[],
            text="",
            error=f"adapter_load_failed: {exc}",
            dispatch_id="",
        )

    # ---- 4. Read packet -----------------------------------------------------
    try:
        packet_content = _read_packet(packet_path)
    except (OSError, ValueError) as exc:
        return DispatchResult(
            success=False,
            engine_used="",
            fallback_chain=[],
            text="",
            error=f"packet_read_failed: {exc}",
            dispatch_id="",
        )

    # ---- 4.5 PACKET-INJECTION-FILTER (2026-05-21) --------------------------
    # Refuse packets that look like they're trying to exfiltrate secrets
    # via env vars / DPAPI calls / outbound HTTP.  Operator can bypass by
    # setting HARNESS_ALLOW_UNSAFE_PACKETS=1 (e.g. for security research).
    if os.environ.get("HARNESS_ALLOW_UNSAFE_PACKETS", "").lower() != "1":
        injections = scan_packet_for_injection(packet_content)
        if injections:
            pattern_names = ",".join(name for name, _ in injections)
            return DispatchResult(
                success=False,
                engine_used="",
                fallback_chain=[],
                text="",
                error=f"packet_injection_blocked: {pattern_names}",
                dispatch_id="",
            )

    # ---- 5. Read engine health (once per dispatch) -------------------------
    try:
        health = state_files.read_engine_health()
    except state_files.StateFileCorruptError as exc:
        return DispatchResult(
            success=False,
            engine_used="",
            fallback_chain=[],
            text="",
            error=f"engine_health_corrupt: {exc}",
            dispatch_id="",
        )

    # ---- 6. Pick initial engine --------------------------------------------
    try:
        initial_engine, rule_model, extra_args = _pick_initial_engine(
            adapter, health, packet_path, force_engine
        )
    except Exception as exc:
        return DispatchResult(
            success=False,
            engine_used="",
            fallback_chain=[],
            text="",
            error=f"engine_selection_failed: {exc}",
            dispatch_id="",
        )

    model = force_model if force_model is not None else rule_model

    # ---- 7. Insert dispatch into history.db ---------------------------------
    try:
        dispatch_id = state_db.insert_dispatch(
            project=project,
            packet_path=packet_path,
            backend=initial_engine,
            model=model,
        )
    except Exception as exc:
        return DispatchResult(
            success=False,
            engine_used=initial_engine,
            fallback_chain=[initial_engine],
            text="",
            error=f"db_insert_failed: {exc}",
            dispatch_id="",
        )

    # ---- 8. Append active dispatch -----------------------------------------
    started_at = _now_iso()
    active_entry = state_files.ActiveDispatch(
        dispatch_id=dispatch_id,
        project=project,
        packet_path=packet_path,
        backend=initial_engine,  # type: ignore[arg-type]
        model=model,
        started_at=started_at,
        status="running",
        fallback_count=0,
        current_backend=initial_engine,
    )
    try:
        state_files.append_active_dispatch(active_entry)
    except Exception:
        pass  # Best-effort; do not block dispatch on state-file write failure.

    # ---- 8b. STATUS tracker hook (opt-in via wave_id) ---------------------
    if wave_id is not None:
        try:
            from harness.status import hooks as _status_hooks
            _status_hooks.on_dispatch_start(
                task_id=dispatch_id,
                wave_id=wave_id,
                engine=initial_engine,
            )
        except Exception:
            pass  # STATUS bookkeeping must never break dispatch.

    # ---- 9. Dispatch loop --------------------------------------------------
    engine_cache: dict[str, Any] = {}
    tried: list[str] = []
    current_engine = initial_engine

    def _cached_engine(name: str) -> Any:
        if name not in engine_cache:
            engine_cache[name] = get_engine(name)
        return engine_cache[name]

    while True:
        tried.append(current_engine)

        # --- 9a. Execute -----------------------------------------------------
        try:
            engine = _cached_engine(current_engine)
            response = engine.dispatch(
                packet_content,
                model or "",
                extra_args or {},
            )
        except Exception:
            # M-2 fix: do NOT interpolate exc — repr() can leak into fallbacks.reason.
            response = EngineResponse(
                success=False,
                text="",
                latency_ms=0,
                error="engine_init_failed",
            )

        # M-3 fix: forensic-signal enrichment BEFORE the success check, so
        # DeepSeek packet-trap / Kimi empty / Anthropic refusal all become
        # success=False and trigger fallback. Without this call, guards.py
        # was unreachable dead code (per ACCEPT-3 wiring promise).
        response = guards.classify_response(
            backend=current_engine,
            model=model,
            packet_content=packet_content,
            response=response,
        )

        # --- 9b. Success path ------------------------------------------------
        if response.success:
            try:
                state_db.update_dispatch_status(
                    dispatch_id, "success", latency_ms=response.latency_ms
                )
            except Exception:
                pass

            _remove_active_dispatch(dispatch_id)

            try:
                jsonl_log.write_log_entry(
                    project=project,
                    packet_path=packet_path,
                    backend=current_engine,
                    model=model,
                    outcome="success",
                    latency_ms=response.latency_ms,
                    fallback_to=None,
                )
            except Exception:
                pass

            if wave_id is not None:
                try:
                    from harness.status import hooks as _status_hooks
                    _status_hooks.on_dispatch_complete(
                        task_id=dispatch_id,
                        wave_id=wave_id,
                        outcome="success",
                    )
                except Exception:
                    pass

            return DispatchResult(
                success=True,
                engine_used=current_engine,
                fallback_chain=list(tried),
                text=response.text,
                error=None,
                dispatch_id=dispatch_id,
                tokens_used=response.tokens_in + response.tokens_out,
                cost_usd=response.cost_usd,
            )

        # --- 9c. Failure path ------------------------------------------------
        # Update engine health only on transition (avoid needless rewrites).
        h = health.get(current_engine)
        if h is None or h.status != "degraded":
            try:
                state_files.update_engine_health(
                    current_engine,
                    {"status": "degraded", "last_fail": _now_iso()},
                )
            except Exception:
                pass
            # Keep local cache in sync for subsequent priority sorts.
            if h is not None:
                h.status = "degraded"  # type: ignore[misc]
                h.last_fail = _now_iso()  # type: ignore[misc]
            else:
                health[current_engine] = state_files.EngineHealth(
                    status="degraded",
                    last_fail=_now_iso(),
                )

        # LOCK refusal: if the failed engine is locked and no other engine
        # is locked, return total failure.
        if h is not None and h.locked:
            other_locked = any(
                other_h.locked
                for other_name, other_h in health.items()
                if other_name != current_engine and other_name in SUPPORTED_BACKENDS
            )
            if not other_locked:
                try:
                    state_db.update_dispatch_status(
                        dispatch_id,
                        "all_fallbacks_exhausted",
                        latency_ms=response.latency_ms,
                    )
                except Exception:
                    pass

                _remove_active_dispatch(dispatch_id)

                try:
                    jsonl_log.write_log_entry(
                        project=project,
                        packet_path=packet_path,
                        backend=current_engine,
                        model=model,
                        outcome="all_fallbacks_exhausted",
                        latency_ms=response.latency_ms,
                        fallback_to=None,
                    )
                except Exception:
                    pass

                if wave_id is not None:
                    try:
                        from harness.status import hooks as _status_hooks
                        _status_hooks.on_dispatch_complete(
                            task_id=dispatch_id,
                            wave_id=wave_id,
                            outcome="failure",
                            notes=f"locked_engine_failed: {response.error}",
                        )
                    except Exception:
                        pass

                return DispatchResult(
                    success=False,
                    engine_used=current_engine,
                    fallback_chain=list(tried),
                    text="",
                    error=f"locked_engine_failed: {response.error}",
                    dispatch_id=dispatch_id,
                )

        # --- 9d. Choose next engine -----------------------------------------
        remaining = [n for n in _production_backends() if n not in tried]
        if not remaining:
            try:
                state_db.update_dispatch_status(
                    dispatch_id,
                    "all_fallbacks_exhausted",
                    latency_ms=response.latency_ms,
                )
            except Exception:
                pass

            _remove_active_dispatch(dispatch_id)

            try:
                jsonl_log.write_log_entry(
                    project=project,
                    packet_path=packet_path,
                    backend=current_engine,
                    model=model,
                    outcome="all_fallbacks_exhausted",
                    latency_ms=response.latency_ms,
                    fallback_to=None,
                )
            except Exception:
                pass

            if wave_id is not None:
                try:
                    from harness.status import hooks as _status_hooks
                    _status_hooks.on_dispatch_complete(
                        task_id=dispatch_id,
                        wave_id=wave_id,
                        outcome="failure",
                        notes=f"all_fallbacks_exhausted: {response.error}",
                    )
                except Exception:
                    pass

            return DispatchResult(
                success=False,
                engine_used=current_engine,
                fallback_chain=list(tried),
                text="",
                error=f"all_fallbacks_exhausted: {response.error}",
                dispatch_id=dispatch_id,
            )

        eligible = _eligible_engines(health, exclude=set(tried))
        next_engine = eligible[0][0] if eligible else remaining[0]

        # --- 9e. Record fallback step ----------------------------------------
        reason = response.error or "unknown"
        try:
            state_db.insert_fallback(
                dispatch_id,
                from_backend=current_engine,
                to_backend=next_engine,
                reason=reason,
            )
        except Exception:
            pass

        try:
            jsonl_log.write_log_entry(
                project=project,
                packet_path=packet_path,
                backend=current_engine,
                model=model,
                outcome="fallback",
                latency_ms=response.latency_ms,
                fallback_to=next_engine,
            )
        except Exception:
            pass

        _update_active_dispatch_fallback(dispatch_id, next_engine)

        current_engine = next_engine
