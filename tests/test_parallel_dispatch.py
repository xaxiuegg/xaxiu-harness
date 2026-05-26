"""W14-PARALLEL-DISPATCH-RETRY-FIX: tests for parallel + serial-retry.

Coverage:
  - All-success path
  - Transient failure retried serially + succeeds
  - Non-transient (auth-failed) NOT retried
  - Terminated NOT retried (account-level)
  - No-key NOT retried (config issue)
  - Multiple tasks, mixed outcomes — order preserved
  - max_serial_retries exhausted → returns last failure
  - Empty task list → empty result
  - Thunk raises → caught + converted to failed response
  - on_retry callback fires + telemetry failures swallowed
  - retry_cooldown_sec=0 doesn't sleep
"""
from __future__ import annotations

import time

import pytest

from harness.engines.base import EngineResponse
from harness.engines.parallel_dispatch import (
    parallel_dispatch_with_serial_retry,
    _is_transient_response,
)


class TestIsTransientResponse:
    def test_success_is_not_transient(self) -> None:
        r = EngineResponse(success=True, text="ok", latency_ms=10)
        assert _is_transient_response(r) is False

    def test_remote_protocol_error_is_transient(self) -> None:
        r = EngineResponse(
            success=False, text="", latency_ms=10,
            error="remote_protocol_error: RemoteProtocolError(...)",
        )
        assert _is_transient_response(r) is True

    def test_timeout_is_transient(self) -> None:
        r = EngineResponse(
            success=False, text="", latency_ms=10,
            error="timeout: ReadTimeout",
        )
        assert _is_transient_response(r) is True

    def test_auth_failed_is_not_transient(self) -> None:
        r = EngineResponse(
            success=False, text="", latency_ms=10, error="HTTP 401",
        )
        assert _is_transient_response(r) is False

    def test_terminated_is_not_transient(self) -> None:
        r = EngineResponse(
            success=False, text="", latency_ms=10,
            error="HTTP 403: Access terminated",
        )
        assert _is_transient_response(r) is False

    def test_no_key_is_not_transient(self) -> None:
        r = EngineResponse(
            success=False, text="", latency_ms=10,
            error="No API key for kimi",
        )
        assert _is_transient_response(r) is False

    def test_endpoint_down_is_transient(self) -> None:
        r = EngineResponse(
            success=False, text="", latency_ms=10, error="HTTP 503",
        )
        # 5xx → endpoint-down → in _TRANSIENT_CATEGORIES
        assert _is_transient_response(r) is True


class TestParallelDispatch:
    def test_empty_tasks_returns_empty(self) -> None:
        assert parallel_dispatch_with_serial_retry([]) == []

    def test_all_success_path(self) -> None:
        def make_task(text):
            return lambda: EngineResponse(
                success=True, text=text, latency_ms=10,
            )
        tasks = [make_task("a"), make_task("b"), make_task("c")]
        results = parallel_dispatch_with_serial_retry(
            tasks, retry_cooldown_sec=0,
        )
        assert len(results) == 3
        # Order preserved
        assert [r.text for r in results] == ["a", "b", "c"]

    def test_transient_retried_and_succeeds(self) -> None:
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] == 1:
                return EngineResponse(
                    success=False, text="", latency_ms=10,
                    error="remote_protocol_error: RemoteProtocolError(x)",
                )
            return EngineResponse(
                success=True, text="recovered", latency_ms=20,
            )

        results = parallel_dispatch_with_serial_retry(
            [flaky], retry_cooldown_sec=0,
        )
        assert results[0].success is True
        assert results[0].text == "recovered"
        assert counter[0] == 2  # 1 parallel + 1 serial retry

    def test_non_transient_not_retried(self) -> None:
        counter = [0]

        def auth_fail():
            counter[0] += 1
            return EngineResponse(
                success=False, text="", latency_ms=10, error="HTTP 401",
            )

        results = parallel_dispatch_with_serial_retry(
            [auth_fail], retry_cooldown_sec=0,
        )
        assert results[0].success is False
        assert counter[0] == 1

    def test_terminated_not_retried(self) -> None:
        counter = [0]

        def terminated():
            counter[0] += 1
            return EngineResponse(
                success=False, text="", latency_ms=10,
                error="HTTP 403: Access terminated",
            )

        results = parallel_dispatch_with_serial_retry(
            [terminated], retry_cooldown_sec=0,
        )
        assert counter[0] == 1

    def test_max_serial_retries_exhausted(self) -> None:
        counter = [0]

        def always_flaky():
            counter[0] += 1
            return EngineResponse(
                success=False, text="", latency_ms=10,
                error="remote_protocol_error: RemoteProtocolError(persistent)",
            )

        results = parallel_dispatch_with_serial_retry(
            [always_flaky], max_serial_retries=2, retry_cooldown_sec=0,
        )
        # 1 parallel + 2 serial retries = 3 total
        assert counter[0] == 3
        assert results[0].success is False

    def test_thunk_exception_caught(self) -> None:
        def bad():
            raise RuntimeError("thunk exploded")

        results = parallel_dispatch_with_serial_retry(
            [bad], retry_cooldown_sec=0,
        )
        assert results[0].success is False
        assert "RuntimeError" in (results[0].error or "")
        assert "thunk exploded" in (results[0].error or "")

    def test_mixed_outcomes_order_preserved(self) -> None:
        counter = [0]

        def good():
            return EngineResponse(success=True, text="A", latency_ms=10)

        def flaky():
            counter[0] += 1
            if counter[0] == 1:
                return EngineResponse(
                    success=False, text="", latency_ms=10,
                    error="remote_protocol_error: RemoteProtocolError(y)",
                )
            return EngineResponse(success=True, text="B", latency_ms=20)

        def auth_fail():
            return EngineResponse(
                success=False, text="", latency_ms=10, error="HTTP 401",
            )

        results = parallel_dispatch_with_serial_retry(
            [good, flaky, auth_fail], retry_cooldown_sec=0,
        )
        assert len(results) == 3
        assert results[0].text == "A"
        assert results[1].text == "B"
        assert results[2].success is False
        assert counter[0] == 2

    def test_on_retry_callback_fires(self) -> None:
        retry_log: list[tuple[int, int, str]] = []

        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] == 1:
                return EngineResponse(
                    success=False, text="", latency_ms=10,
                    error="remote_protocol_error: RemoteProtocolError(z)",
                )
            return EngineResponse(success=True, text="OK", latency_ms=20)

        def cb(task_index: int, attempt: int, error: str) -> None:
            retry_log.append((task_index, attempt, error))

        parallel_dispatch_with_serial_retry(
            [flaky], retry_cooldown_sec=0, on_retry=cb,
        )
        assert len(retry_log) == 1
        assert retry_log[0][0] == 0
        assert retry_log[0][1] == 1

    def test_on_retry_callback_failure_does_not_break_retry(self) -> None:
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] == 1:
                return EngineResponse(
                    success=False, text="", latency_ms=10,
                    error="remote_protocol_error: RemoteProtocolError(w)",
                )
            return EngineResponse(success=True, text="done", latency_ms=20)

        def broken_cb(*args, **kwargs):
            raise RuntimeError("callback exploded")

        results = parallel_dispatch_with_serial_retry(
            [flaky], retry_cooldown_sec=0, on_retry=broken_cb,
        )
        assert results[0].success is True
        assert counter[0] == 2

    def test_cooldown_zero_does_not_sleep(self) -> None:
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] == 1:
                return EngineResponse(
                    success=False, text="", latency_ms=10,
                    error="remote_protocol_error: RemoteProtocolError(v)",
                )
            return EngineResponse(success=True, text="x", latency_ms=20)

        start = time.monotonic()
        parallel_dispatch_with_serial_retry(
            [flaky], retry_cooldown_sec=0,
        )
        elapsed = time.monotonic() - start
        assert elapsed < 0.5

    def test_concurrent_parallel_execution(self) -> None:
        def slow():
            time.sleep(0.1)
            return EngineResponse(success=True, text="ok", latency_ms=100)

        tasks = [slow] * 4
        start = time.monotonic()
        results = parallel_dispatch_with_serial_retry(
            tasks, max_workers=4, retry_cooldown_sec=0,
        )
        elapsed = time.monotonic() - start
        assert all(r.success for r in results)
        # Parallel: ~100ms; sequential would be ~400ms.  Allow 350ms for CI.
        assert elapsed < 0.35, f"expected parallel ~0.1s, got {elapsed:.2f}s"
