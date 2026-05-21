"""CLI helper functions — factored out to keep cli.py under 500 lines."""

from __future__ import annotations

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
