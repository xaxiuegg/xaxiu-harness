"""Concrete engine implementation for Google Gemini.

Endpoint: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent

Honoured ``extra_args``:
    - ``temperature`` (float) – defaults to 0.2 if not provided.
    - ``max_output_tokens`` (int) – defaults to 8192 if not provided.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx
from httpx import Timeout

from harness import __version__
from harness.engines.base import Engine, EngineResponse

_DEFAULT_TIMEOUT = Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

GEMINI_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _make_user_agent() -> str:
    """Return User-Agent header value: ``xaxiu-harness/<version>``."""
    return f"xaxiu-harness/{__version__}"


def _extract_gemini_text(response_data: dict) -> str:
    """Extract text from Gemini generateContent response."""
    candidates = response_data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


class GeminiConcrete(Engine):
    """Concrete engine for Google Gemini API."""

    default_model = "gemini-2.0-flash"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "gemini"

    def dispatch(
        self,
        packet_content: str,
        model: str,
        extra_args: Optional[dict[str, Any]] = None,
    ) -> EngineResponse:
        if not self._api_key:
            return EngineResponse(
                success=False,
                text="",
                latency_ms=0,
                error="missing_api_key",
            )

        extra = extra_args or {}
        effective_model = model or self.default_model

        # W13-ENGINE-RETRY-RESILIENT 2026-05-25: shared retry helper.
        # Auto-retry once on transient httpx errors; preserve repr(exc)
        # for non-transient ones (replaces the prior bare except).
        from harness.engines._retry import run_with_retry

        def _do_http() -> EngineResponse:
            start = time.monotonic()
            with httpx.Client(
                verify=True,
                timeout=_DEFAULT_TIMEOUT,
            ) as client:
                payload = self._build_payload(packet_content, effective_model, extra)
                response = client.post(
                    GEMINI_ENDPOINT_TEMPLATE.format(model=effective_model),
                    params={"key": self._api_key},
                    headers={
                        "User-Agent": _make_user_agent(),
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    return EngineResponse(
                        success=False,
                        text="",
                        latency_ms=latency_ms,
                        error="no_candidates",
                    )
                text = _extract_gemini_text(data)
                latency_ms = int((time.monotonic() - start) * 1000)
                return EngineResponse(
                    success=True,
                    text=text,
                    latency_ms=latency_ms,
                    error=None,
                )

        return run_with_retry(_do_http)

    @staticmethod
    def _build_payload(
        content: str,
        model: str,
        extra: dict[str, Any],
    ) -> dict:
        temperature = extra.get("temperature", 0.2)
        max_output_tokens = extra.get("max_output_tokens", 8192)
        return {
            "contents": [
                {"role": "user", "parts": [{"text": content}]}
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
