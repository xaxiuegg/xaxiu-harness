"""CLI helper functions — factored out to keep cli.py under 500 lines."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from harness._constants import SUPPORTED_BACKENDS
from harness.engines.concrete import get_engine


_ENGINE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "kimi": "https://api.moonshot.cn",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
}

# Backends that have a real network endpoint to probe.  The "mock" backend
# is local-only — it has no upstream URL and is always reachable, so it is
# excluded from health probes.  Kept module-private so other modules use
# ``SUPPORTED_BACKENDS`` (the full universe) explicitly.
_PROBEABLE_BACKENDS: list[str] = [b for b in SUPPORTED_BACKENDS if b in _ENGINE_URLS]


def probe_engine(name: str) -> tuple[str, str | None]:
    """Return (status, error_or_none) for a single engine.

    Steps:
    1. Try to instantiate the engine via ``get_engine`` (validates API key).
    2. Issue a lightweight HTTP GET to the provider's base URL to check
       network connectivity.
    """
    try:
        get_engine(name)
    except RuntimeError as exc:
        return "down", str(exc)

    url = _ENGINE_URLS.get(name)
    if not url:
        return "down", f"Unknown engine: {name}"

    try:
        with httpx.Client(timeout=5.0) as client:
            client.get(url, headers={"User-Agent": "xaxiu-harness/health"})
            # Any response (even 404) means the network layer is up.
            return "up", None
    except httpx.ConnectError:
        return "down", "network"
    except httpx.TimeoutException:
        return "down", "timeout"
    except Exception as exc:
        return "down", str(exc)


def probe_engine_quota(name: str) -> dict[str, str | int | None]:
    """Probe an engine + extract rate-limit / quota headers if present.

    ENGINE-PROBE-QUOTA (2026-05-21).  Most providers return
    ``X-RateLimit-Remaining`` / ``X-RateLimit-Limit`` / ``X-RateLimit-Reset``
    on responses; this helper surfaces them so the operator can spot
    silent throttling.  Returns a dict with status + the parsed quota
    fields (each may be None if the provider didn't include them).
    """
    quota: dict[str, str | int | None] = {
        "status": "down",
        "limit": None,
        "remaining": None,
        "reset": None,
        "raw_status_code": None,
        "error": None,
    }

    try:
        get_engine(name)
    except RuntimeError as exc:
        quota["error"] = str(exc)
        return quota

    url = _ENGINE_URLS.get(name)
    if not url:
        quota["error"] = f"Unknown engine: {name}"
        return quota

    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(url, headers={"User-Agent": "xaxiu-harness/health"})
            quota["status"] = "up"
            quota["raw_status_code"] = r.status_code
            # Common rate-limit header names — providers spell them slightly differently
            for key in ("x-ratelimit-limit", "x-ratelimit-limit-requests"):
                v = r.headers.get(key)
                if v is not None:
                    try:
                        quota["limit"] = int(v)
                    except ValueError:
                        quota["limit"] = v
                    break
            for key in ("x-ratelimit-remaining", "x-ratelimit-remaining-requests"):
                v = r.headers.get(key)
                if v is not None:
                    try:
                        quota["remaining"] = int(v)
                    except ValueError:
                        quota["remaining"] = v
                    break
            for key in ("x-ratelimit-reset", "x-ratelimit-reset-requests"):
                v = r.headers.get(key)
                if v is not None:
                    quota["reset"] = v
                    break
    except httpx.ConnectError:
        quota["error"] = "network"
    except httpx.TimeoutException:
        quota["error"] = "timeout"
    except Exception as exc:
        quota["error"] = str(exc)

    return quota


def probe_all_engines() -> dict[str, tuple[str, str | None]]:
    """Probe every network-backed backend and return a status mapping.

    The "mock" backend has no network endpoint and is intentionally omitted
    from the result — it is always available locally.
    """
    return {name: probe_engine(name) for name in _PROBEABLE_BACKENDS}


def probe_all_engines_quota() -> dict[str, dict[str, str | int | None]]:
    """Probe each network-backed backend with quota header parsing."""
    return {name: probe_engine_quota(name) for name in _PROBEABLE_BACKENDS}


# ---------------------------------------------------------------------------
# W13-ENGINE-FAILURE-VISIBILITY: live probe + failure categorization.
#
# The legacy shallow probe (``probe_engine``) only does a network GET to the
# provider's base URL — any HTTP response (even 403 "Access terminated")
# counts as "up", because the host is reachable.  This makes auth-side
# failures invisible until the operator runs a real dispatch and gets
# burned mid-panel (Kimi account-termination case 2026-05-25).
#
# ``probe_engine_live`` does a real ~5-token dispatch and categorizes the
# response so operators see the actual liveness state, not just reachability.
# Probe results are appended to ``state/engine_health_probes.jsonl`` so they
# accumulate as a time-series — separate from the production-dispatch log
# (``state/engine_performance_log.jsonl``) because they serve different
# purposes (probes are operator-initiated; dispatches are production-traffic).
# ---------------------------------------------------------------------------


_HEALTH_PROBE_LOG: str = "state/engine_health_probes.jsonl"


# Category vocabulary — closed set, ordered roughly worst→best for display.
ENGINE_HEALTH_CATEGORIES: tuple[str, ...] = (
    "terminated",       # account or API key revoked at provider
    "auth-failed",      # 401, key invalid for endpoint, key missing
    "quota-exceeded",   # 429, rate-limit, plan/balance exhausted
    "endpoint-down",    # 5xx, DNS, connection refused
    "transient",        # network blip, RemoteProtocolError, timeout
    "no-key",           # local: env var missing, DPAPI empty
    "unknown-failure",  # error didn't match any pattern
    "up",               # success
)


def categorize_engine_failure(
    success: bool,
    error_str: str | None,
) -> str:
    """Categorize an engine dispatch outcome into a vocabulary bucket.

    Pure function — no I/O, no env reads.  Designed to be called with
    ``(EngineResponse.success, EngineResponse.error)`` from any dispatch
    path.

    Returns one of ``ENGINE_HEALTH_CATEGORIES``.

    Categorization is best-effort substring/regex matching on the
    error text.  When the upstream changes their error string we
    update the patterns here.

    Examples
    --------
    >>> categorize_engine_failure(True, None)
    'up'
    >>> categorize_engine_failure(False, "HTTP 403: Access terminated")
    'terminated'
    >>> categorize_engine_failure(False, "HTTP 401")
    'auth-failed'
    >>> categorize_engine_failure(False, "no api key for kimi")
    'no-key'
    >>> categorize_engine_failure(False, "RemoteProtocolError")
    'transient'
    """
    if success:
        return "up"
    if error_str is None:
        return "unknown-failure"
    text = error_str.lower()
    # Order matters: "Access terminated" must beat the generic "403" rule.
    if "access terminated" in text or "account_terminated" in text:
        return "terminated"
    if "access_terminated_error" in text:
        return "terminated"
    if "no api key" in text or "missing api key" in text \
            or "key_not_found" in text:
        return "no-key"
    if re.search(r"\bhttp 401\b", text) or "invalid_authentication" in text \
            or "invalid authentication" in text or "unauthorized" in text \
            or "invalid_api_key" in text:
        return "auth-failed"
    if re.search(r"\bhttp 4(03|07)\b", text):
        # 403/407 with no "terminated" marker — bucket as auth-failed
        return "auth-failed"
    if re.search(r"\bhttp 429\b", text) or "rate limit" in text \
            or "rate_limit" in text or "quota" in text \
            or "balance" in text or "insufficient" in text:
        return "quota-exceeded"
    if re.search(r"\bhttp 5\d\d\b", text) or "internal server error" in text \
            or "bad gateway" in text or "service unavailable" in text \
            or "gateway timeout" in text:
        return "endpoint-down"
    if "connecterror" in text or "connection refused" in text \
            or "name or service not known" in text \
            or "dns" in text or "getaddrinfo" in text:
        return "endpoint-down"
    if "remoteprotocolerror" in text or "server disconnected" in text \
            or "timeout" in text or "timed out" in text \
            or "read timeout" in text:
        return "transient"
    return "unknown-failure"


def _redact_for_probe_log(error_str: str | None) -> str | None:
    """Redaction for probe-log error excerpts.

    The live probe could surface error strings that include bits of the
    API key (rare, but some providers echo a redacted key in 401 bodies).
    Drop any sk-* / tp-* / AIza* / bearer-* tokens before logging.
    """
    if not error_str:
        return error_str
    s = error_str[:300]  # excerpt cap
    s = re.sub(r"sk-[A-Za-z0-9_\-]{4,}", "sk-[REDACTED]", s)
    s = re.sub(r"tp-[A-Za-z0-9_\-]{4,}", "tp-[REDACTED]", s)
    s = re.sub(r"AIza[A-Za-z0-9_\-]{4,}", "AIza[REDACTED]", s)
    s = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]{4,}", "Bearer [REDACTED]", s,
               flags=re.IGNORECASE)
    return s


def _append_probe_event(
    engine: str,
    category: str,
    error_str: str | None,
    latency_ms: int,
    *,
    log_path: Path | None = None,
) -> None:
    """Append one health-probe row to ``state/engine_health_probes.jsonl``.

    Best-effort: NEVER raises.  If the path can't be written we silently
    skip — health probing must not break the CLI.
    """
    try:
        path = log_path or (Path.cwd() / _HEALTH_PROBE_LOG)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "engine": engine,
            "category": category,
            "error_excerpt": _redact_for_probe_log(error_str),
            "latency_ms": int(latency_ms),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
            f.write("\n")
    except Exception:
        # Health probing is read-mostly diagnostics; never block on log errors.
        return


def probe_engine_live(
    name: str,
    *,
    log: bool = True,
    log_path: Path | None = None,
) -> tuple[str, str | None]:
    """Do a real ~5-token dispatch against ``name`` and categorize the result.

    Returns ``(category, error_or_none)`` where category is one of
    ``ENGINE_HEALTH_CATEGORIES``.

    Parameters
    ----------
    name : str
        Engine name (one of ``SUPPORTED_BACKENDS``).
    log : bool
        Whether to append the probe outcome to the health-probes JSONL.
        Tests pass ``log=False`` to avoid filesystem side effects.
    log_path : Path, optional
        Override the log path (test isolation).

    Notes
    -----
    The probe uses ``max_tokens=5`` to keep cost negligible.  The exact
    model used is the engine's default; we don't try alternate models
    since the goal is "does the operator's normal config work right now",
    not "is any model available".
    """
    start = time.monotonic()
    # Step 1: instantiate the engine (catches missing-key case)
    try:
        eng = get_engine(name)
    except RuntimeError as exc:
        category = categorize_engine_failure(False, str(exc))
        latency_ms = int((time.monotonic() - start) * 1000)
        if log:
            _append_probe_event(name, category, str(exc), latency_ms,
                                log_path=log_path)
        return category, str(exc)

    # Step 2: pick a default model per engine (cheap echo)
    default_models = {
        "deepseek": "deepseek-v4-flash",
        "kimi": "kimi-for-coding",
        "mimo": "mimo-v2.5-pro",
        "anthropic": "claude-haiku-4-5-20251001",
        "gemini": "gemini-2.0-flash-exp",
    }
    model = default_models.get(name, name)

    # Step 3: dispatch a tiny prompt
    try:
        resp = eng.dispatch("ok", model, {"max_tokens": 5})
    except Exception as exc:
        category = categorize_engine_failure(False, f"{type(exc).__name__}: {exc}")
        latency_ms = int((time.monotonic() - start) * 1000)
        err_excerpt = f"{type(exc).__name__}: {exc}"
        if log:
            _append_probe_event(name, category, err_excerpt, latency_ms,
                                log_path=log_path)
        return category, err_excerpt

    latency_ms = int((time.monotonic() - start) * 1000)
    # Empty content with max_tokens=5 is valid (engine truncated cleanly);
    # don't require non-empty text to consider the dispatch successful.
    success = bool(resp.success)
    category = categorize_engine_failure(success, resp.error)
    err_excerpt = resp.error if not success else None
    if log:
        _append_probe_event(name, category, err_excerpt, latency_ms,
                            log_path=log_path)
    return category, err_excerpt


def probe_all_engines_live(
    *,
    log: bool = True,
    log_path: Path | None = None,
) -> dict[str, tuple[str, str | None]]:
    """Live-probe every network-backed engine.  Sequential (not parallel)
    to avoid hitting rate-limits during a routine ``engines --health``.

    Covers every ``SUPPORTED_BACKENDS`` except ``mock`` (always-local) —
    including engines (like ``mimo``) that don't have a fixed base URL
    for the shallow ``probe_engine`` path.  The live probe doesn't need
    a base URL because the engine adapter resolves its own endpoint.
    """
    targets = [b for b in SUPPORTED_BACKENDS if b != "mock"]
    return {
        name: probe_engine_live(name, log=log, log_path=log_path)
        for name in targets
    }


def read_failure_summary(
    *,
    since_hours: int = 168,
    engine: str | None = None,
    dispatch_log_path: Path | None = None,
    probe_log_path: Path | None = None,
) -> dict:
    """Read both dispatch + probe logs and aggregate failure counts.

    Returns a dict::

        {
            "since_hours": 168,
            "engines": {
                "kimi": {
                    "total": 50,
                    "by_category": {"terminated": 12, "up": 38},
                    "recent_samples": [...]
                },
                ...
            }
        }

    Categorization for the dispatch log (which only has outcome buckets
    like ``api_error``) is fuzzy — we can only mark them as
    ``api_error`` / ``timeout`` / ``success``.  The probe log has full
    categorization.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
    cwd = Path.cwd()
    paths = [
        (dispatch_log_path or (cwd / "state" / "engine_performance_log.jsonl"),
         "dispatch"),
        (probe_log_path or (cwd / _HEALTH_PROBE_LOG), "probe"),
    ]

    engines: dict[str, dict] = {}

    for path, source in paths:
        if not path.exists():
            continue
        try:
            for line in path.read_text(
                encoding="utf-8", errors="replace",
            ).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Parse timestamp
                ts = rec.get("timestamp")
                if not ts:
                    continue
                try:
                    rec_ts = datetime.fromisoformat(
                        ts.replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError):
                    continue
                if rec_ts < cutoff:
                    continue
                # Engine name lives in different fields per source
                eng = rec.get("engine") or rec.get("backend")
                if not eng:
                    continue
                if engine and eng != engine:
                    continue
                # Category derivation
                if source == "probe":
                    category = rec.get("category", "unknown")
                else:
                    # Dispatch log: outcome buckets
                    outcome = rec.get("outcome", "unknown")
                    if outcome == "success":
                        category = "up"
                    elif outcome in ("timeout",):
                        category = "transient"
                    elif outcome in ("api_error", "packet_trap",
                                     "fallback", "all_fallbacks_exhausted"):
                        category = "api_error"  # generic — can't subclassify
                    else:
                        category = outcome
                slot = engines.setdefault(eng, {
                    "total": 0,
                    "by_category": {},
                    "recent_samples": [],
                })
                slot["total"] += 1
                slot["by_category"][category] = \
                    slot["by_category"].get(category, 0) + 1
                # Keep last 5 non-success samples for display
                if category != "up" and len(slot["recent_samples"]) < 5:
                    slot["recent_samples"].append({
                        "timestamp": ts,
                        "source": source,
                        "category": category,
                        "error_excerpt": rec.get("error_excerpt")
                            or rec.get("outcome"),
                    })
        except OSError:
            continue

    return {
        "since_hours": since_hours,
        "engines": engines,
    }
