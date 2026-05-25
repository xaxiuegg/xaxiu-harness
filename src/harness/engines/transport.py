"""W7-B1-RETROFIT: StreamingTransport ABC for SSE engines.

Consolidates the SSE-streaming dispatch loop shared by DeepSeek and
Kimi.  MiMo is intentionally out of scope (it uses non-streaming
``client.post() + response.json()``).

Background: the W5-V wiring fix had to be applied THREE times because
the SSE parse loop was inline in each engine.  Architect feedback from
the 5-MiMo session review identified this as the #1 source of
bug-class duplication.  W6-B1 dispatched a refactor but the worker
stalled mid-step on the engine retrofit; W7-B1-RETROFIT picks it up.

Template-method pattern:

  ``dispatch()`` owns the streaming loop, prefix handling, [DONE]
  terminator, chunk JSON-decode, error mapping.

  Subclasses provide endpoint, headers, payload, and optionally
  override two hooks for engine-specific behavior:

    - ``_process_delta`` — capture engine-specific fields beyond
      ``content`` (Kimi captures ``reasoning_content``).
    - ``_finalize_response`` — build the final ``EngineResponse``
      from the accumulated chunks (Kimi sets ``reasoning_only``).

  A third optional hook, ``_handle_remote_protocol_error``, lets
  subclasses rescue partial content when the server disconnects
  mid-stream (Kimi: ``kimi_remote_disconnect`` recovery).
"""

from __future__ import annotations

import json
import time
from abc import abstractmethod
from typing import Any, Optional

import httpx

from harness.engines.base import Engine, EngineResponse


# Re-import the per-engine timeout constant from concrete (avoids
# duplicating the Timeout instance and keeps a single source of truth).
def _default_timeout() -> httpx.Timeout:
    # Late import to dodge a potential circular: concrete imports
    # transport when subclasses move there.
    from harness.engines.concrete import _DEFAULT_TIMEOUT
    return _DEFAULT_TIMEOUT


class StreamingTransport(Engine):
    """Engine subclass that owns the OpenAI-compat SSE streaming loop.

    Subclasses must implement:
      - :meth:`_endpoint_url`
      - :meth:`_headers`
      - :meth:`_build_payload`

    Subclasses MAY override:
      - :meth:`_process_delta` — engine-specific delta fields
      - :meth:`_finalize_response` — engine-specific EngineResponse
      - :meth:`_handle_remote_protocol_error` — partial-content rescue
    """

    # -- abstract: subclasses MUST implement -----------------------------------

    @abstractmethod
    def _endpoint_url(self) -> str:
        """Return the streaming endpoint URL."""

    @abstractmethod
    def _headers(self) -> dict[str, str]:
        """Return the HTTP headers for this engine."""

    @abstractmethod
    def _build_payload(
        self, content: str, model: str, extra: dict[str, Any],
    ) -> dict:
        """Return the request body.  Caller adds ``stream=True``."""

    # -- overridable: defaults match DeepSeek's behavior -----------------------

    def _process_delta(self, delta: dict, accumulated: dict) -> None:
        """Capture fields from one chunk's ``delta`` block.

        Default: append ``delta.content`` to ``accumulated["content_chunks"]``.
        Subclasses (Kimi) may capture extra fields like ``reasoning_content``.
        """
        if delta.get("content"):
            accumulated.setdefault("content_chunks", []).append(
                delta["content"]
            )

    def _finalize_response(
        self,
        accumulated: dict,
        latency_ms: int,
        usage_info: Optional[dict],
        finish_reason: str,
    ) -> EngineResponse:
        """Build the EngineResponse from accumulated chunks + usage.

        Default: standard OpenAI-compat response.  Subclasses may
        override to set engine-specific fields (Kimi sets
        ``reasoning_only`` when content_chunks is empty but
        reasoning_chunks isn't).
        """
        text = "".join(accumulated.get("content_chunks", []))
        tokens_in = int((usage_info or {}).get("prompt_tokens", 0))
        tokens_out = int((usage_info or {}).get("completion_tokens", 0))
        parsed_anything = (
            bool(accumulated.get("content_chunks"))
            or usage_info is not None
            or bool(finish_reason)
        )
        if not parsed_anything:
            return EngineResponse(
                success=False, text="", latency_ms=latency_ms,
                error="parse_error_no_chunks",
            )
        return EngineResponse(
            success=True, text=text, latency_ms=latency_ms,
            error=None, tokens_in=tokens_in, tokens_out=tokens_out,
        )

    def _handle_remote_protocol_error(
        self, accumulated: dict, latency_ms: int,
    ) -> Optional[EngineResponse]:
        """Optional: rescue partial content on mid-stream disconnect.

        Default: return None — base class re-raises the error path
        as ``error="internal"``.  Kimi overrides this to return a
        partial-success EngineResponse with whatever content was
        already streamed.
        """
        return None

    # -- template: orchestrates the SSE streaming loop -------------------------

    def dispatch(
        self,
        packet_content: str,
        model: str,
        extra_args: Optional[dict[str, Any]] = None,
    ) -> EngineResponse:
        extra = extra_args or {}
        payload = self._build_payload(packet_content, model, extra)
        payload["stream"] = True  # W5-MM / W5-V: SSE only

        url = self._endpoint_url()
        headers = self._headers()

        # W13-ENGINE-RETRY-RESILIENT 2026-05-25: shared retry helper.
        # Streaming has one nuance vs the other engines: on
        # ``RemoteProtocolError`` Kimi can RESCUE accumulated partial
        # content via ``_handle_remote_protocol_error``.  Preserve
        # that — if rescue returns a partial-success response, return
        # it directly (no retry, we already got content).  Only when
        # rescue returns None do we re-raise so the outer helper can
        # retry the whole stream.
        from harness.engines._retry import run_with_retry

        def _do_stream() -> EngineResponse:
            start = time.monotonic()
            accumulated: dict[str, Any] = {}
            usage_info: Optional[dict] = None
            finish_reason: str = ""
            try:
                with httpx.Client(
                    verify=True, timeout=_default_timeout(),
                ) as client:
                    with client.stream(
                        "POST", url, headers=headers, json=payload,
                    ) as response:
                        if response.status_code != 200:
                            # Explicit non-200 — don't retry; just
                            # surface the status (auth failures etc).
                            latency_ms = int((time.monotonic() - start) * 1000)
                            return EngineResponse(
                                success=False, text="",
                                latency_ms=latency_ms,
                                error=f"HTTP {response.status_code}",
                            )
                        for line in response.iter_lines():
                            if not line:
                                continue
                            # W5-V / W5-MM: both "data: " (standard) and
                            # "data:" (Kimi's non-standard) variants.
                            if line.startswith("data: "):
                                data_str = line[6:]
                            elif line.startswith("data:"):
                                data_str = line[5:]
                            else:
                                continue
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                            except (ValueError, json.JSONDecodeError):
                                continue
                            choices = chunk.get("choices") or []
                            if choices:
                                delta = choices[0].get("delta") or {}
                                self._process_delta(delta, accumulated)
                                fr = choices[0].get("finish_reason")
                                if fr:
                                    finish_reason = fr
                            if chunk.get("usage"):
                                usage_info = chunk["usage"]
                latency_ms = int((time.monotonic() - start) * 1000)
                return self._finalize_response(
                    accumulated, latency_ms, usage_info, finish_reason,
                )
            except httpx.RemoteProtocolError:
                # Streaming-specific: try to rescue accumulated partial
                # content BEFORE retrying.  Kimi overrides this to
                # return a partial-success response.  If rescue returns
                # a response, we use it (no retry).  If None, re-raise
                # so run_with_retry treats this as a transient error
                # and retries the whole stream once.
                latency_ms = int((time.monotonic() - start) * 1000)
                rescued = self._handle_remote_protocol_error(
                    accumulated, latency_ms,
                )
                if rescued is not None:
                    return rescued
                raise  # let run_with_retry catch + retry

        return run_with_retry(_do_stream)
