"""W14-PARALLEL-DISPATCH-RETRY-FIX 2026-05-26: parallel dispatch with
serial-retry fallback for transient failures.

The harness's panel-style workflow (release-gate, master-plan, evaluation
panels) fires N engine dispatches concurrently via ThreadPoolExecutor.
Each engine has its own per-HTTP retry via ``harness.engines._retry``,
but that retry happens INSIDE the parallel race — if the parallel pool
is the source of contention (MiMo's regularly-observed
``RemoteProtocolError`` pattern), the in-HTTP retry burns its single
attempt against the same race and fails twice.

This module provides ``parallel_dispatch_with_serial_retry`` — a thin
wrapper around ThreadPoolExecutor that, after the parallel pass
completes, retries failed-transient tasks SERIALLY.  The serial pass
runs without the race, so engines that "always work on retry" (per the
W13-ENGINE-RETRY-RESILIENT investigation: 12/12 MiMo retries succeeded)
get their retry in the right environment.

Categorization uses the W13-ENGINE-FAILURE-VISIBILITY
``categorize_engine_failure`` so the retry decision matches the rest
of the system's failure taxonomy.

The N panel scripts (v1_release_gate_panel.py,
post_v1_master_plan_panel.py, pattern_b_evaluation_panel.py) can now
delete their ad-hoc ``_retry_one`` helpers in favor of this canonical
implementation.

The mid-panel MiMo failure on 2026-05-26's Pattern B evaluation panel
(3/3 retries of mimo/operational-risk failed in parallel + the serial
retry only worked when run outside the ThreadPoolExecutor context) is
the concrete bug this row fixes.
"""
from __future__ import annotations

import concurrent.futures as _cf
import logging
import time
from typing import Callable, Optional

from harness.engines.base import EngineResponse

logger = logging.getLogger(__name__)


# Error-category buckets that warrant a serial retry.  Pulled from the
# W13-ENGINE-FAILURE-VISIBILITY closed vocabulary.  We intentionally do
# NOT retry "terminated" (account-level — won't recover), "auth-failed"
# (key invalid — won't recover), or "no-key" (config — won't recover).
# "endpoint-down" is borderline; included because a 5xx might be
# load-shedding that resolves with a beat of patience.
_TRANSIENT_CATEGORIES: frozenset[str] = frozenset({
    "transient",
    "endpoint-down",
    "quota-exceeded",  # often a rate-limit blip; retry after backoff
})


def _is_transient_response(resp: EngineResponse) -> bool:
    """Use the W13 categorizer to decide if a failed EngineResponse is
    worth retrying serially."""
    if resp.success:
        return False
    # Import lazily to keep this module's import graph small + decoupled
    from harness.cli_helpers import categorize_engine_failure
    category = categorize_engine_failure(resp.success, resp.error)
    return category in _TRANSIENT_CATEGORIES


def parallel_dispatch_with_serial_retry(
    tasks: list[Callable[[], EngineResponse]],
    *,
    max_workers: int = 4,
    max_serial_retries: int = 2,
    retry_cooldown_sec: float = 1.0,
    on_retry: Optional[Callable[[int, int, str], None]] = None,
) -> list[EngineResponse]:
    """Run ``tasks`` in parallel; serially retry transient failures.

    Args:
      tasks: list of thunks; each returns an ``EngineResponse``.
        Order is preserved — ``result[i]`` is the response for
        ``tasks[i]`` regardless of completion order.
      max_workers: ThreadPoolExecutor concurrency.  Default 4 matches
        the subprocess semaphore default.
      max_serial_retries: how many SERIAL passes to run AFTER the
        parallel pass for transient failures.  Default 2 (so up to 3
        total attempts: 1 parallel + 2 serial).  The W13 investigation
        showed 12/12 transient errors resolved within 2 retries.
      retry_cooldown_sec: sleep before each serial retry pass.
        Default 1.0s.  Prevents hammering a stressed provider.
      on_retry: optional callback ``(task_index, attempt_no, error)``
        called before each serial retry.  Used by panel scripts for
        progress reporting.  Failures in the callback are swallowed —
        never break the retry loop.

    Returns:
      List of ``EngineResponse``, one per task, in input order.
      Failed tasks get the LAST attempt's response.

    Never raises.  Exceptions from individual thunks are caught and
    converted to failed EngineResponse with the exception text.
    """
    n = len(tasks)
    results: list[Optional[EngineResponse]] = [None] * n

    # ---- Round 1: parallel ----
    if n > 0:
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_idx = {pool.submit(t): i for i, t in enumerate(tasks)}
            for future in _cf.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except BaseException as exc:
                    # The thunk itself raised (not an EngineResponse with
                    # error=...).  Convert to failed response so the
                    # serial-retry loop can decide whether to retry.
                    results[idx] = EngineResponse(
                        success=False,
                        text="",
                        latency_ms=0,
                        error=f"{type(exc).__name__}: {exc}",
                    )

    # ---- Rounds 2..N: serial retries for transient failures ----
    for serial_attempt in range(1, max_serial_retries + 1):
        retry_indices = [
            i for i, r in enumerate(results)
            if r is not None and _is_transient_response(r)
        ]
        if not retry_indices:
            break
        if retry_cooldown_sec > 0:
            time.sleep(retry_cooldown_sec)
        for i in retry_indices:
            prev_err = (results[i].error if results[i] is not None
                        else "no response")
            if on_retry is not None:
                try:
                    on_retry(i, serial_attempt, prev_err or "")
                except Exception:
                    pass  # Telemetry must never break retry loop
            logger.info(
                "parallel_dispatch serial retry attempt=%d task_idx=%d "
                "prev_error=%r",
                serial_attempt, i, (prev_err or "")[:200],
            )
            try:
                results[i] = tasks[i]()
            except BaseException as exc:
                results[i] = EngineResponse(
                    success=False,
                    text="",
                    latency_ms=0,
                    error=f"{type(exc).__name__}: {exc}",
                )

    # All slots must be populated by now (None only possible when n=0)
    final_results: list[EngineResponse] = []
    for r in results:
        if r is None:
            final_results.append(EngineResponse(
                success=False, text="", latency_ms=0,
                error="parallel_dispatch: no result produced",
            ))
        else:
            final_results.append(r)
    return final_results
