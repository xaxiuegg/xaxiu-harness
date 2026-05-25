"""W13-ENGINE-RETRY-RESILIENT: tests for the shared retry helper.

Covers:
  - categorize_exception correctly identifies transient vs non-transient
  - run_with_retry: success on first attempt
  - run_with_retry: transient fail → retry → success
  - run_with_retry: transient fail → retry → fail (preserves last error)
  - run_with_retry: non-transient fail → no retry (preserves error)
  - run_with_retry: bare Exception → no retry, repr preserved
  - run_with_retry: cooldown actually waits
  - run_with_retry: on_retry callback fires with right args
  - regression: bare 'internal' error string is GONE
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import httpx
import pytest

from harness.engines._retry import (
    categorize_exception,
    run_with_retry,
    TRANSIENT_HTTPX_TYPES,
)
from harness.engines.base import EngineResponse


# -- categorize_exception ---------------------------------------------------


def _fake_response(status: int) -> httpx.Response:
    """Build a minimal httpx.Response for HTTPStatusError tests."""
    req = httpx.Request("POST", "https://example.com/")
    return httpx.Response(status, request=req)


class TestCategorize:
    def test_http_status_error_404_not_transient(self):
        err = httpx.HTTPStatusError(
            "404", request=httpx.Request("GET", "https://x/"),
            response=_fake_response(404),
        )
        msg, transient = categorize_exception(err)
        assert "404" in msg
        assert transient is False

    def test_http_status_error_500_not_transient(self):
        # Even server-side errors don't auto-retry — they're explicit
        # responses, not transport-level issues
        err = httpx.HTTPStatusError(
            "500", request=httpx.Request("GET", "https://x/"),
            response=_fake_response(500),
        )
        msg, transient = categorize_exception(err)
        assert "500" in msg
        assert transient is False

    def test_remote_protocol_error_is_transient(self):
        err = httpx.RemoteProtocolError("Server disconnected")
        msg, transient = categorize_exception(err)
        assert "remote_protocol_error" in msg
        assert "Server disconnected" in msg
        assert transient is True

    def test_timeout_is_transient(self):
        err = httpx.TimeoutException("read timeout")
        msg, transient = categorize_exception(err)
        assert "timeout" in msg
        assert transient is True

    def test_read_timeout_subclass_is_transient(self):
        err = httpx.ReadTimeout("read timed out")
        msg, transient = categorize_exception(err)
        assert "timeout" in msg
        assert "ReadTimeout" in msg
        assert transient is True

    def test_connect_timeout_is_transient(self):
        err = httpx.ConnectTimeout("connect timed out")
        msg, transient = categorize_exception(err)
        assert transient is True

    def test_pool_timeout_is_transient(self):
        err = httpx.PoolTimeout("pool exhausted")
        msg, transient = categorize_exception(err)
        assert transient is True

    def test_connect_error_not_transient(self):
        # ConnectError (TCP refusal / DNS failure) — single retry
        # won't fix it; operator needs to investigate
        err = httpx.ConnectError("connection refused")
        msg, transient = categorize_exception(err)
        assert "network" in msg
        assert transient is False

    def test_unknown_exception_preserves_type_name(self):
        # Replaces the old bare-except "internal" — the actual type
        # must be visible to the operator now
        err = ValueError("something weird happened")
        msg, transient = categorize_exception(err)
        assert "unexpected" in msg
        assert "ValueError" in msg
        assert "something weird" in msg
        assert transient is False

    def test_unknown_exception_does_not_say_internal(self):
        """REGRESSION: the bare 'internal' string from the prior wrapper
        must not appear in the new error categorization."""
        for exc in [ValueError("x"), RuntimeError("y"), TypeError("z")]:
            msg, _ = categorize_exception(exc)
            assert msg != "internal", (
                f"regression: {type(exc).__name__} still returning 'internal'"
            )

    def test_transient_types_constant_matches_classifier(self):
        """Sanity: the TRANSIENT_HTTPX_TYPES constant should classify
        as transient via the classifier."""
        # Build one of each transient type
        for cls in TRANSIENT_HTTPX_TYPES:
            try:
                exc = cls("test")
            except TypeError:
                continue  # constructor needs more args; skip
            _, transient = categorize_exception(exc)
            assert transient, f"{cls.__name__} should be transient"


# -- run_with_retry ---------------------------------------------------------


def _success_response(text: str = "ok") -> EngineResponse:
    return EngineResponse(success=True, text=text, latency_ms=10, error=None)


class TestRunWithRetry:
    def test_success_first_attempt_no_retry(self):
        calls = []

        def fn() -> EngineResponse:
            calls.append("call")
            return _success_response("hello")

        result = run_with_retry(fn, cooldown_sec=0)
        assert result.success is True
        assert result.text == "hello"
        assert len(calls) == 1  # only one attempt

    def test_transient_then_success_retries_once(self):
        """The load-bearing case: RemoteProtocolError → retry → success."""
        attempt = {"n": 0}

        def fn() -> EngineResponse:
            attempt["n"] += 1
            if attempt["n"] == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return _success_response("eventual ok")

        result = run_with_retry(fn, cooldown_sec=0)
        assert result.success is True
        assert result.text == "eventual ok"
        assert attempt["n"] == 2

    def test_transient_twice_returns_failure_with_last_error(self):
        attempt = {"n": 0}

        def fn() -> EngineResponse:
            attempt["n"] += 1
            raise httpx.RemoteProtocolError(f"disconnect #{attempt['n']}")

        result = run_with_retry(fn, cooldown_sec=0)
        assert result.success is False
        # Last attempt's error preserved
        assert "remote_protocol_error" in result.error
        # We attempted exactly 2 times (1 original + 1 retry)
        assert attempt["n"] == 2

    def test_http_status_error_does_not_retry(self):
        """REGRESSION: a 401 should NOT loop the auth path."""
        attempt = {"n": 0}

        def fn() -> EngineResponse:
            attempt["n"] += 1
            raise httpx.HTTPStatusError(
                "401", request=httpx.Request("GET", "https://x/"),
                response=_fake_response(401),
            )

        result = run_with_retry(fn, cooldown_sec=0)
        assert result.success is False
        assert "401" in result.error
        assert attempt["n"] == 1  # NO retry on HTTP errors

    def test_unknown_exception_does_not_retry(self):
        attempt = {"n": 0}

        def fn() -> EngineResponse:
            attempt["n"] += 1
            raise ValueError("something weird")

        result = run_with_retry(fn, cooldown_sec=0)
        assert result.success is False
        assert "ValueError" in result.error
        assert "something weird" in result.error
        assert attempt["n"] == 1  # NO retry on unknown errors

    def test_timeout_is_transient_and_retries(self):
        attempt = {"n": 0}

        def fn() -> EngineResponse:
            attempt["n"] += 1
            if attempt["n"] == 1:
                raise httpx.ReadTimeout("first read timed out")
            return _success_response()

        result = run_with_retry(fn, cooldown_sec=0)
        assert result.success is True
        assert attempt["n"] == 2

    def test_max_retries_zero_means_no_retry(self):
        attempt = {"n": 0}

        def fn() -> EngineResponse:
            attempt["n"] += 1
            raise httpx.RemoteProtocolError("transient")

        result = run_with_retry(fn, max_retries=0, cooldown_sec=0)
        assert result.success is False
        assert attempt["n"] == 1  # no retry when max_retries=0

    def test_max_retries_two_allows_three_attempts(self):
        attempt = {"n": 0}

        def fn() -> EngineResponse:
            attempt["n"] += 1
            if attempt["n"] < 3:
                raise httpx.RemoteProtocolError("transient")
            return _success_response()

        result = run_with_retry(fn, max_retries=2, cooldown_sec=0)
        assert result.success is True
        assert attempt["n"] == 3

    def test_cooldown_actually_waits(self):
        """Cool-down between retries must be honored."""
        attempt = {"n": 0}

        def fn() -> EngineResponse:
            attempt["n"] += 1
            if attempt["n"] == 1:
                raise httpx.RemoteProtocolError("retry me")
            return _success_response()

        started = time.monotonic()
        result = run_with_retry(fn, cooldown_sec=0.2)
        elapsed = time.monotonic() - started
        assert result.success is True
        # Should have waited at least 200ms
        assert elapsed >= 0.18, f"cooldown ignored: {elapsed:.3f}s"

    def test_on_retry_callback_fires_with_args(self):
        captured: list[tuple] = []

        def on_retry(err_str: str, attempt_no: int) -> None:
            captured.append((err_str, attempt_no))

        attempts = {"n": 0}

        def fn() -> EngineResponse:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.RemoteProtocolError("flake")
            return _success_response()

        run_with_retry(fn, cooldown_sec=0, on_retry=on_retry)
        assert len(captured) == 1
        err_str, n = captured[0]
        assert "remote_protocol_error" in err_str
        assert n == 1  # first retry is attempt #1

    def test_on_retry_callback_failure_does_not_break_retry(self):
        """Telemetry callback raising must not break the retry path."""
        def broken_cb(err: str, n: int) -> None:
            raise RuntimeError("telemetry exploded")

        attempts = {"n": 0}

        def fn() -> EngineResponse:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.RemoteProtocolError("flake")
            return _success_response("recovered")

        result = run_with_retry(fn, cooldown_sec=0, on_retry=broken_cb)
        assert result.success is True
        assert result.text == "recovered"

    def test_failure_response_returned_not_raised(self):
        """run_with_retry NEVER raises — even non-transient unknown
        exceptions become EngineResponse(success=False)."""

        def fn() -> EngineResponse:
            raise RuntimeError("totally unexpected")

        result = run_with_retry(fn, cooldown_sec=0)
        assert isinstance(result, EngineResponse)
        assert result.success is False
        assert "RuntimeError" in result.error
        assert "totally unexpected" in result.error

    def test_latency_ms_accumulates_across_attempts(self):
        """The reported latency_ms includes the cooldown + all attempts."""
        def fn() -> EngineResponse:
            raise httpx.RemoteProtocolError("flake")

        result = run_with_retry(fn, cooldown_sec=0.1)
        # 2 attempts + 0.1s cooldown between them = >100ms total
        assert result.latency_ms >= 90, (
            f"latency under-reported: {result.latency_ms}ms"
        )


# -- regression sentinels ---------------------------------------------------


def test_no_bare_internal_in_categorize():
    """Strong regression: categorize_exception must never return the
    bare string 'internal' that the old bare-except did."""
    for exc in [
        ValueError("a"),
        RuntimeError("b"),
        TypeError("c"),
        KeyError("d"),
        OSError("e"),
        httpx.ConnectError("f"),
        httpx.HTTPStatusError(
            "g", request=httpx.Request("GET", "https://x/"),
            response=_fake_response(500),
        ),
    ]:
        msg, _ = categorize_exception(exc)
        assert msg != "internal", (
            f"{type(exc).__name__} returned bare 'internal'"
        )


def test_run_with_retry_failure_error_is_never_bare_internal():
    """The error field of the failure response must always be more
    descriptive than the prior 'internal'."""
    def fn() -> EngineResponse:
        raise ValueError("x")

    result = run_with_retry(fn, cooldown_sec=0)
    assert result.success is False
    assert result.error != "internal"
    assert "ValueError" in result.error


# -- End-to-end regression: original MiMo failure mode -----------------------


def test_mimo_engine_retries_on_remote_protocol_error_end_to_end():
    """W13 regression: simulate the exact MiMo failure mode from the
    investigation (RemoteProtocolError on first attempt) and verify
    the engine returns success after the retry.

    Before W13-ENGINE-RETRY-RESILIENT this would have returned the
    opaque 'internal' error from the bare-except.  After the fix,
    the engine retries once and returns the success response.
    """
    from unittest.mock import patch, MagicMock
    from harness.engines.concrete import MiMoConcrete

    # First call raises RemoteProtocolError; second call returns 200
    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.RemoteProtocolError("Server disconnected")
        # Second attempt: return a fake 200 response
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={
            "choices": [{"message": {"content": "recovered after retry"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        })
        return resp

    class _FakeClient:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def post(self, *a, **k):
            return fake_post(*a, **k)

    with patch("httpx.Client", _FakeClient):
        # Set an api_key so MiMoConcrete doesn't reject the call
        engine = MiMoConcrete(api_key="sk-test")
        resp = engine.dispatch("test prompt", "mimo-v2.5-pro",
                                {"max_tokens": 100})

    assert resp.success is True, (
        f"engine did not retry on RemoteProtocolError: "
        f"error={resp.error}, calls={call_count['n']}"
    )
    assert "recovered after retry" in resp.text
    assert call_count["n"] == 2  # original + 1 retry


def test_mimo_engine_persistent_transient_returns_descriptive_error():
    """If retries are exhausted, the error must NOT be the old bare
    'internal' string — it must include the exception type + repr."""
    from unittest.mock import patch
    from harness.engines.concrete import MiMoConcrete

    class _FakeClient:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def post(self, *a, **k):
            raise httpx.RemoteProtocolError("persistent disconnect")

    with patch("httpx.Client", _FakeClient):
        engine = MiMoConcrete(api_key="sk-test")
        resp = engine.dispatch("test", "mimo-v2.5-pro", {"max_tokens": 100})

    assert resp.success is False
    assert resp.error != "internal", (
        "regression: bare 'internal' string returned"
    )
    assert "remote_protocol_error" in resp.error
    assert "persistent disconnect" in resp.error
