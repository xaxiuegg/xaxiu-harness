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
#
# WIRE-ENGINE-TIMEOUT (2026-05-22): read=120 was too tight for thinking-heavy
# models.  Artificial Analysis 2026-05-22 benchmark shows real end-to-end
# response times:
#   - Kimi K2.6           63.53s
#   - DeepSeek V4 Pro Max 165.45s   ← biggest outlier; 120s would have killed it
#   - DeepSeek V4 Pro Hi   84.60s
#   - DeepSeek V4 Flash    56.61s
#   - MiMo-V2.5-Pro        46.94s
#   - MiMo-V2.5            29.93s
# 600s gives ~4x headroom over the slowest practical engine.  Operators
# who want a tighter cap for dev loops can override via the per-call
# `timeout_s` extra_arg (honoured in each engine below) or by setting
# HARNESS_ENGINE_READ_TIMEOUT_S in the environment.
# ---------------------------------------------------------------------------
_DEFAULT_READ_TIMEOUT_S: float = float(
    os.environ.get("HARNESS_ENGINE_READ_TIMEOUT_S", "600")
)
_DEFAULT_TIMEOUT = Timeout(
    connect=10.0, read=_DEFAULT_READ_TIMEOUT_S, write=10.0, pool=10.0,
)


def _make_user_agent() -> str:
    """Return User-Agent header value: ``xaxiu-harness/<version>``."""
    return f"xaxiu-harness/{__version__}"


def _make_kimi_user_agent() -> str:
    """Kimi Code API requires a whitelisted User-Agent (gate per
    ``reference_kimi_features_canonical``).  Default to ``claude-code/0.1.0``
    which is verified-working from inside Claude Code sessions; override
    via ``KIMI_USER_AGENT`` for other approved agents
    (e.g. ``KimiCLI/1.5``).
    """
    return os.environ.get("KIMI_USER_AGENT", "claude-code/0.1.0")


def _resolve_kimi_upstream() -> str:
    """Resolve the Kimi chat-completions endpoint.

    Per ``reference_kimi_features_canonical``, there are THREE distinct
    Kimi services:

    1. **Kimi Code** (kimi.ai) — `https://api.kimi.com/coding/v1` —
       subscription-quota with User-Agent gate.  **This is the operator's
       account** (battle-test 2026-05-21).
    2. **Kimi Platform** (moonshot.ai) — `https://api.moonshot.ai/v1` —
       international pay-as-you-go.
    3. **Moonshot China** (moonshot.cn) — `https://api.moonshot.cn/v1` —
       China-region pay-as-you-go.

    API keys are NOT interchangeable; the URL must match the key's
    issuing platform.  Resolution precedence:

    1. ``HARNESS_PROXY_URL`` — explicit operator override (highest)
    2. Local proxy at `.harness/proxy.pid` (set by ``harness proxy start``)
    3. ``KIMI_API_BASE_URL`` env var (operator-set base; we append the
       chat-completions path)
    4. ``KIMI_BASE_URL`` env var (Kimi-CLI convention; same shape)
    5. Default: Kimi Code at ``api.kimi.com/coding/v1``
    """
    explicit = os.environ.get("HARNESS_PROXY_URL")
    if explicit:
        return explicit
    pid_file = Path(".harness") / "proxy.pid"
    if pid_file.exists():
        return "http://127.0.0.1:7879/v1/chat/completions"
    base = (
        os.environ.get("KIMI_API_BASE_URL")
        or os.environ.get("KIMI_BASE_URL")
        or ""
    ).rstrip("/")
    if base:
        # Operator gave a base — append the chat path if not already present
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"
    # Default to Kimi Code (kimi.ai) — operator account confirmed 2026-05-21
    return "https://api.kimi.com/coding/v1/chat/completions"


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
        # WIRE-MAX-TOKENS (2026-05-22): explicit max_tokens unblocks the
        # server-side default cap (DeepSeek/Kimi both top out around
        # 16K-32K when omitted) so long responses aren't silently
        # truncated mid-edit.  Default 32768 gives ~2x typical worker
        # output without burning the full 131K cap.
        max_tokens = int(extra.get("max_tokens", 32768))
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "max_tokens": max_tokens,
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
                        # Kimi Code API enforces a User-Agent allowlist —
                        # see _make_kimi_user_agent docstring.
                        "User-Agent": _make_kimi_user_agent(),
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
        # WIRE-MAX-TOKENS (2026-05-22): Kimi Code's default output cap is
        # ~16K when omitted, which silently truncates long worker
        # outputs.  Explicit 32K gives headroom without bloating the
        # context budget.  Kimi K2.6 supports up to 256K total context
        # so this leaves plenty of room for the input prompt.
        max_tokens = int(extra.get("max_tokens", 32768))
        return {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "max_tokens": max_tokens,
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
# MiMo (Xiaomi)
# ---------------------------------------------------------------------------

def _resolve_mimo_upstream(api_key: str) -> str:
    """Pick the MiMo endpoint based on key prefix + region + env overrides.

    Xiaomi runs the Token Plan against TWO regional gateways
    (verified 2026-05-22 from platform.xiaomimimo.com/docs/tokenplan):
      - ``token-plan-ams.xiaomimimo.com`` — Amsterdam (international, default)
      - ``token-plan-cn.xiaomimimo.com``  — China

    Pay-as-you-go is unified at ``api.xiaomimimo.com``.

    Resolution order:
      1. ``MIMO_BASE_URL`` env var (full URL override)
      2. ``MIMO_REGION`` env var: ``cn`` → cn gateway; anything else → ams
      3. Key prefix: ``tp-`` → Token Plan; ``sk-`` / other → pay-as-you-go
    """
    explicit = os.environ.get("MIMO_BASE_URL", "").strip()
    if explicit:
        url = explicit.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = url + "/chat/completions"
        return url
    region = os.environ.get("MIMO_REGION", "ams").strip().lower()
    if api_key.startswith("tp-"):
        if region == "cn":
            return "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
        return "https://token-plan-ams.xiaomimimo.com/v1/chat/completions"
    return "https://api.xiaomimimo.com/v1/chat/completions"


def _make_mimo_user_agent() -> str:
    """User-Agent for MiMo Token Plan TOS compliance.

    Xiaomi's Token Plan terms restrict use to coding harnesses
    (OpenClaw, OpenCode, Claude Code, KiloCode...).  Like Kimi Coding API,
    the gate is enforced at the User-Agent level.  Default matches
    Kimi's working value (``claude-code/0.1.0``); operators can override
    via ``MIMO_USER_AGENT`` when they're calling from a different
    approved coding tool.

    The pay-as-you-go endpoint does not enforce the gate, but sending
    the same UA there is harmless and keeps one code path.
    """
    return os.environ.get("MIMO_USER_AGENT", "claude-code/0.1.0")


class MiMoConcrete(Engine):
    """Concrete engine for Xiaomi MiMo Open Platform (V2.5 / V2.5-Pro).

    Endpoint: ``https://api.xiaomimimo.com/v1/chat/completions`` (pay-as-you-go)
    or ``https://token-plan-cn.xiaomimimo.com/v1/chat/completions`` (Token Plan
    subscription, auto-selected when the API key starts with ``tp-``).

    Honoured ``extra_args``:
      - ``temperature`` (float) – defaults to 0.6
      - ``max_tokens`` (int) – defaults to 32768 (MiMo caps at 131072)
      - ``thinking`` (bool) – passed through if present
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
                    _resolve_mimo_upstream(self._api_key),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        # MiMo Token Plan TOS gate — see
                        # _make_mimo_user_agent docstring.
                        "User-Agent": _make_mimo_user_agent(),
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
        temperature = float(extra.get("temperature", 0.6))
        max_tokens = int(extra.get("max_tokens", 32768))
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if "thinking" in extra:
            payload["thinking"] = bool(extra["thinking"])
        return payload


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
    elif name_lower == "mimo":
        cls = MiMoConcrete
    else:
        # Should not happen due to earlier guard, but keep exhaustive.
        raise RuntimeError(f"Unsupported engine: {name_lower}")

    return cls(api_key=api_key)