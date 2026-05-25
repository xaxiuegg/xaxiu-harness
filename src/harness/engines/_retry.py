"""W13-ENGINE-RETRY-RESILIENT: shared retry + error-categorization
helper for engine adapters.

Per the MiMo investigation (2026-05-25, commits 5b61566 + 53af024):
the per-engine `dispatch()` methods used a bare ``except Exception:``
that masked all errors as the opaque string ``"internal"``.  The
investigation found:

  - 12/12 retries of "failing" MiMo configurations succeeded —
    failures were transient ``RemoteProtocolError`` events, not
    deterministic content or size triggers
  - The bare-except hid the real exception type, making the failures
    look like content-filter issues when they were just transient API
    flakes

This helper centralizes the right behavior:

  1. Catch each httpx exception type explicitly
  2. Preserve ``repr(exc)`` in the error field for debuggability
  3. Retry ONCE on the known-transient types (RemoteProtocolError,
     TimeoutException) after a brief cool-down
  4. Do NOT retry on explicit server responses (HTTPStatusError) or
     hard client errors (ConnectError, unknown exceptions) — those
     either won't resolve on retry, or shouldn't loop without
     operator awareness

Usage:

    from harness.engines._retry import run_with_retry

    def dispatch(self, packet_content, model, extra_args=None):
        extra = extra_args or {}

        def _do_http() -> EngineResponse:
            start = time.monotonic()
            with httpx.Client(...) as client:
                # ... do the actual HTTP work, return success
                return EngineResponse(success=True, ...)

        return run_with_retry(_do_http)

The thunk pattern preserves each engine's existing HTTP logic
unchanged — only the error-handling wrapper changes.

Note on KimiEngine: that engine has additional success-path nuance
(partial accumulated text from incomplete streams becomes "success
with text" not failure) — it owns its own try/except inside the
StreamingTransport.dispatch, so its overriding behavior is preserved
when StreamingTransport uses this helper.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from harness.engines.base import EngineResponse

# Transient errors we retry once after a brief cool-down.
# - RemoteProtocolError: server closed connection mid-stream (the
#   load-bearing case from the MiMo investigation)
# - TimeoutException (and subclasses: ReadTimeout, ConnectTimeout,
#   WriteTimeout, PoolTimeout) — client-side wait limit
TRANSIENT_HTTPX_TYPES: tuple[type[BaseException], ...] = (
    httpx.RemoteProtocolError,
    httpx.TimeoutException,
)


def categorize_exception(exc: BaseException) -> tuple[str, bool]:
    """Return ``(error_string, is_transient)`` for an exception.

    Args:
        exc: the caught exception

    Returns:
        ``(error_string, is_transient)``:
          - ``error_string`` preserves the original exception type +
            repr, so the operator + audit log can see what actually
            happened (vs the old opaque "internal")
          - ``is_transient`` tells the retry loop whether to attempt
            another call

    Categories:
      - ``HTTPStatusError``: explicit server response (4xx/5xx) →
        retry would just re-hit the same response.  NOT transient.
      - ``RemoteProtocolError``: server disconnected mid-response.
        Empirically resolves on retry per W13 investigation.
        TRANSIENT.
      - ``TimeoutException`` (incl. ReadTimeout, ConnectTimeout, etc):
        wait exceeded.  May be transient under load.  TRANSIENT.
      - ``ConnectError``: TCP refusal or DNS failure.  Almost always
        a config/network issue that retry won't fix.  NOT transient.
      - Any other ``BaseException``: unknown.  NOT transient (don't
        mask a bug as flakiness).
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else "?"
        return (f"HTTP {status}", False)
    if isinstance(exc, httpx.RemoteProtocolError):
        return (f"remote_protocol_error: {exc!r}", True)
    if isinstance(exc, httpx.TimeoutException):
        # Includes ConnectTimeout, ReadTimeout, WriteTimeout, PoolTimeout
        kind = type(exc).__name__
        return (f"timeout: {kind}: {exc!r}", True)
    if isinstance(exc, httpx.ConnectError):
        return (f"network: {exc!r}", False)
    # Catch-all (replaces the prior bare "internal").  This preserves
    # the actual exception class so debugging is possible.
    return (f"unexpected: {type(exc).__name__}: {exc!r}", False)


def run_with_retry(
    dispatch_fn: Callable[[], EngineResponse],
    *,
    max_retries: int = 1,
    cooldown_sec: float = 0.5,
    on_retry: Optional[Callable[[str, int], None]] = None,
) -> EngineResponse:
    """Run ``dispatch_fn``; retry once on transient httpx errors.

    Args:
        dispatch_fn: a thunk that performs the HTTP call and returns
            an ``EngineResponse``.  If the call succeeds, it returns
            ``EngineResponse(success=True, ...)``.  If the HTTP layer
            raises, this helper catches + categorizes.
        max_retries: total RETRIES beyond the first attempt.  Default
            1, meaning up to 2 attempts total.  W13 investigation
            showed single retry resolves the vast majority of MiMo
            transient errors.
        cooldown_sec: sleep between attempts so we don't hammer a
            recovering server.  Default 0.5s.
        on_retry: optional callback called after a transient failure
            triggers a retry.  Receives ``(error_string, attempt_no)``
            where attempt_no is 1-indexed (1 = first retry).  Used by
            the future audit-jsonl integration to log retry events.

    Returns:
        The successful ``EngineResponse`` if any attempt succeeded,
        OR a failure ``EngineResponse`` with the LAST attempt's
        error string preserved.

    Never raises — all exceptions are caught and converted to
    failure responses.
    """
    start = time.monotonic()
    last_error_str = "no attempts made"
    for attempt in range(max_retries + 1):
        try:
            return dispatch_fn()
        except BaseException as exc:
            error_str, is_transient = categorize_exception(exc)
            last_error_str = error_str
            # If we have retries left AND this is a transient error,
            # cool down and try again.
            if attempt < max_retries and is_transient:
                if on_retry is not None:
                    try:
                        on_retry(error_str, attempt + 1)
                    except Exception:
                        pass  # Telemetry callback failures must never break the retry loop — best-effort observability path.
                if cooldown_sec > 0:
                    time.sleep(cooldown_sec)
                continue
            # Exhausted retries, or non-transient → return failure
            break

    latency_ms = int((time.monotonic() - start) * 1000)
    return EngineResponse(
        success=False,
        text="",
        latency_ms=latency_ms,
        error=last_error_str,
    )
