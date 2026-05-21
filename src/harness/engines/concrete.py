"""
Concrete engine implementations for DeepSeek, Kimi, and Anthropic.

Each engine subclasses `Engine` from `harness.engines.base` and performs
real HTTP API dispatch via httpx, respecting the security hardening
requirements from v1.2 amendments (HIGH-8, HIGH-9, HIGH-7).

Factory: `get_engine()` resolves the API key from DPAPI or environment,
then returns the appropriate concrete instance.

Usage:
    from harness.engines.concrete import get_engine
    engine = get_engine("deepseek")
    response = engine.dispatch("Hello", "deepseek-v4-flash", {})
"""

import time
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from httpx import Timeout

from harness import __version__
from harness._constants import API_KEY_ENV_VARS
from harness.engines.base import Engine, EngineResponse
from harness.engines.gemini import GeminiConcrete
from harness.engines.mock import MockEngine
from harness.secrets import dpapi


# Sourced from harness._constants — single source of truth, avoids the
# drift risk flagged in Wave 2B batch-1 audit MED-1.
_ENV_VAR_MAP: dict[str, str] = API_KEY_ENV_VARS

# ---------------------------------------------------------------------------
# Timeout configuration (connect, read, write, pool)
# ---------------------------------------------------------------------------
_DEFAULT_TIMEOUT = Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


def _make_user_agent() -> str:
    """Return User-Agent header value: ``xaxiu-harness/<version>``."""
    return f"xaxiu-harness/{__version__}"


def _resolve_kimi_upstream() -> str:
    """Route through local proxy when available, else direct.

    Battle-test 2026-05-21: `api.moonshot.cn` is the China endpoint;
    international accounts (sk- keys issued via moonshot.ai) need
    `api.moonshot.ai` and reject .cn-region requests with HTTP 401.
    Allow operator override via ``KIMI_API_BASE_URL`` env var so the
    key region matches the URL region.
    """
    explicit = os.environ.get("HARNESS_PROXY_URL")
    if explicit:
        return explicit
    pid_file = Path(".harness") / "proxy.pid"
    if pid_file.exists():
        return "http://127.0.0.1:7879/v1/chat/completions"
    base = os.environ.get("KIMI_API_BASE_URL", "").rstrip("/")
    if base:
        return f"{base}/v1/chat/completions"
    return "https://api.moonshot.cn/v1/chat/completions"


def _extract_chat_text(response_data: dict) -> str:
    """Extract content from OpenAI-style chat completions response."""
    choices = response_data.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return message.get("content", "")


def _extract_anthropic_text(response_data: dict) -> str:
    """Extract text from Anthropic Messages API response."""
    content_blocks = response_data.get("content", [])
    if not content_blocks:
        return ""
    # Anthropic returns list of content blocks; we take the first text block
    for block in content_blocks:
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


# ---------------------------------------------------------------------------
# Concrete engine classes
# ---------------------------------------------------------------------------

class DeepSeekConcrete(Engine):
    """Concrete engine for DeepSeek chat completions.

    Endpoint: https://api.deepseek.com/v1/chat/completions

    Honoured `extra_args`:
        - ``--no-thinking`` (bool) – force temperature=0.0 and ``thinking: False``.
        - If model name ends with ``-flash`` the same behaviour is applied
          automatically (v1.2 HIGH-7 mitigation for v4-flash packet traps).
    """

    def dispatch(
        self,
        packet_content: str,
        model: str,
        extra_args: Optional[dict[str, Any]] = None,
    ) -> EngineResponse:
        extra = extra_args or {}

        start = time.monotonic()
        try:
            with httpx.Client(
                verify=True,
                timeout=_DEFAULT_TIMEOUT,
            ) as client:
                payload = self._build_payload(packet_content, model, extra)
                response = client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "User-Agent": _make_user_agent(),
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                text = _extract_chat_text(data)
                latency_ms = int((time.monotonic() - start) * 1000)
                return EngineResponse(
                    success=True,
                    text=text,
                    latency_ms=latency_ms,
                    error=None,
                )
        except httpx.HTTPStatusError as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error=f"HTTP {e.response.status_code}",
            )
        except httpx.TimeoutException:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="timeout",
            )
        except httpx.ConnectError:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="network",
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="internal",
            )

    @staticmethod
    def _build_payload(
        content: str,
        model: str,
        extra: dict[str, Any],
    ) -> dict:
        no_thinking = extra.get("--no-thinking", False) or model.endswith("-flash")
        temperature = 0.0 if no_thinking else 0.6
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
        }
        if no_thinking:
            payload["thinking"] = False
        return payload


class KimiConcrete(Engine):
    """Concrete engine for Kimi (Moonshot) chat completions.

    Endpoint: https://api.moonshot.cn/v1/chat/completions

    Honoured `extra_args`:
        - ``temperature`` (float) – defaults to 0.6 if not provided.
    """

    def dispatch(
        self,
        packet_content: str,
        model: str,
        extra_args: Optional[dict[str, Any]] = None,
    ) -> EngineResponse:
        extra = extra_args or {}

        start = time.monotonic()
        try:
            with httpx.Client(
                verify=True,
                timeout=_DEFAULT_TIMEOUT,
            ) as client:
                payload = self._build_payload(packet_content, model, extra)
                response = client.post(
                    _resolve_kimi_upstream(),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "User-Agent": _make_user_agent(),
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                text = _extract_chat_text(data)
                latency_ms = int((time.monotonic() - start) * 1000)
                return EngineResponse(
                    success=True,
                    text=text,
                    latency_ms=latency_ms,
                    error=None,
                )
        except httpx.HTTPStatusError as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error=f"HTTP {e.response.status_code}",
            )
        except httpx.TimeoutException:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="timeout",
            )
        except httpx.ConnectError:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="network",
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="internal",
            )

    @staticmethod
    def _build_payload(
        content: str,
        model: str,
        extra: dict[str, Any],
    ) -> dict:
        temperature = extra.get("temperature", 0.6)
        return {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
        }


class AnthropicConcrete(Engine):
    """Concrete engine for Anthropic Messages API.

    Endpoint: https://api.anthropic.com/v1/messages

    Honoured `extra_args`:
        - ``max_tokens`` (int) – defaults to 8192 if not provided.
    """

    def dispatch(
        self,
        packet_content: str,
        model: str,
        extra_args: Optional[dict[str, Any]] = None,
    ) -> EngineResponse:
        extra = extra_args or {}

        start = time.monotonic()
        try:
            with httpx.Client(
                verify=True,
                timeout=_DEFAULT_TIMEOUT,
            ) as client:
                payload = self._build_payload(packet_content, model, extra)
                response = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "User-Agent": _make_user_agent(),
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                text = _extract_anthropic_text(data)
                latency_ms = int((time.monotonic() - start) * 1000)
                return EngineResponse(
                    success=True,
                    text=text,
                    latency_ms=latency_ms,
                    error=None,
                )
        except httpx.HTTPStatusError as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error=f"HTTP {e.response.status_code}",
            )
        except httpx.TimeoutException:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="timeout",
            )
        except httpx.ConnectError:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="network",
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False,
                text="",
                latency_ms=latency_ms,
                error="internal",
            )

    @staticmethod
    def _build_payload(
        content: str,
        model: str,
        extra: dict[str, Any],
    ) -> dict:
        max_tokens = extra.get("max_tokens", 8192)
        return {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_engine(name: str, *, prefer_dpapi: bool = True) -> Engine:
    """Return a concrete engine instance for the given backend name.

    Resolves the API key:
      1. If ``prefer_dpapi=True`` and the DPAPI store has a secret for the
         corresponding env var, decrypt and use it.
      2. Otherwise fall back to ``os.environ``.
      3. If no key is found, raise ``RuntimeError`` without leaking the
         attempted key value.

    Args:
        name: One of ``"deepseek"``, ``"kimi"``, ``"anthropic"``, ``"gemini"``.
        prefer_dpapi: Try DPAPI first (default True).

    Returns:
        A concrete ``Engine`` subclass instance.

    Raises:
        RuntimeError: If the engine name is unknown or no API key is available.
    """
    name_lower = name.lower().strip()

    if name_lower == "mock":
        return MockEngine()

    if name_lower not in _ENV_VAR_MAP:
        raise RuntimeError(
            f"Unknown engine '{name}'. Supported: {list(_ENV_VAR_MAP.keys())}"
        )

    env_var = _ENV_VAR_MAP[name_lower]
    api_key: Optional[str] = None

    if prefer_dpapi and dpapi.has_secret(env_var):
        api_key = dpapi.decrypt_secret(env_var)
    else:
        api_key = os.environ.get(env_var)

    if not api_key:
        raise RuntimeError(
            f"No API key for {name_lower}. Run `harness env` to verify."
        )

    cls: type[Engine]
    if name_lower == "deepseek":
        cls = DeepSeekConcrete
    elif name_lower == "kimi":
        cls = KimiConcrete
    elif name_lower == "anthropic":
        cls = AnthropicConcrete
    elif name_lower == "gemini":
        cls = GeminiConcrete
    else:
        # Should not happen due to earlier guard, but keep exhaustive.
        raise RuntimeError(f"Unsupported engine: {name_lower}")

    return cls(api_key=api_key)