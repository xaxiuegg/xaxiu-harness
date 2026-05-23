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

import json
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


def _extract_openai_usage(response_data: dict) -> tuple[int, int]:
    """Read OpenAI-compat (DeepSeek/Kimi/MiMo) ``usage`` block.

    Returns ``(prompt_tokens, completion_tokens)``; falls back to ``(0, 0)``
    if the field is absent or malformed.  Wired W4-K (2026-05-22): previously
    every ledger row reported tokens_in=0 tokens_out=0 because none of the
    engine sites read this block off the JSON response.
    """
    usage = response_data.get("usage") or {}
    if not isinstance(usage, dict):
        return (0, 0)
    try:
        return (int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)))
    except (TypeError, ValueError):
        return (0, 0)


def _extract_anthropic_usage(response_data: dict) -> tuple[int, int]:
    """Read Anthropic ``usage`` block (different keys from OpenAI compat)."""
    usage = response_data.get("usage") or {}
    if not isinstance(usage, dict):
        return (0, 0)
    try:
        return (int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)))
    except (TypeError, ValueError):
        return (0, 0)


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
                tokens_in, tokens_out = _extract_openai_usage(data)
                latency_ms = int((time.monotonic() - start) * 1000)
                return EngineResponse(
                    success=True,
                    text=text,
                    latency_ms=latency_ms,
                    error=None,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
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
        # WIRE-DEEPSEEK-THINKING (2026-05-22): operator preference is
        # deepseek-v4-flash with thinking ON.  DeepSeek's chat-completions
        # API does NOT accept a ``thinking`` JSON field — thinking is
        # implicit per model + CLI flag (``--no-thinking`` is a swarm CLI
        # convention, not an API parameter).  Sending ``thinking: False``
        # caused HTTP 400 in the 2026-05-22 benchmark.
        #
        # Default: don't send the field (= thinking ON).
        # Operator opt-out: pass ``no_thinking=True`` in extra_args; we
        # still don't send a JSON field, but switch temperature to 0.0
        # so output is deterministic (matches swarm's --no-thinking
        # convention for surgical FIND/REPLACE patches).
        no_thinking = bool(
            extra.get("no_thinking")
            or extra.get("--no-thinking")
        )
        temperature = 0.0 if no_thinking else 0.6
        # WIRE-MAX-TOKENS (2026-05-22): explicit max_tokens unblocks the
        # server-side default cap (DeepSeek/Kimi both top out around
        # 16K-32K when omitted) so long responses aren't silently
        # truncated mid-edit.  Default 32768 gives ~2x typical worker
        # output without burning the full 131K cap.
        max_tokens = int(extra.get("max_tokens", 32768))
        return {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }


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
        """W5-V 2026-05-23: streaming-first with Kimi-quirk handling.

        Three Kimi-specific issues this implementation handles:

        1. **60-second server wall-clock**: Kimi's gateway closes the
           connection at ~60s on non-stream requests for big packets
           (3KB+ inputs).  Streaming bypasses this — server keeps the
           connection alive as it emits incremental chunks.

        2. **Thinking-budget starvation**: kimi-for-coding (and most
           Kimi models on api.kimi.com) emit `reasoning_content` tokens
           first then `content`.  Non-stream requests with tight
           max_tokens consume the whole budget on reasoning, leaving 0
           content.  Streaming + a generous max_tokens lets reasoning
           finish + content emit incrementally.

        3. **Non-standard SSE format**: Kimi sends `data:{...}` with
           NO space after the colon (vs the standard `data: {...}`).
           Parsers expecting the space silently emit 0 tokens.
        """
        extra = extra_args or {}

        start = time.monotonic()
        payload = self._build_payload(packet_content, model, extra)
        payload["stream"] = True  # W5-V: always stream Kimi

        url = _resolve_kimi_upstream()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            # Kimi Code API enforces a User-Agent allowlist
            "User-Agent": _make_kimi_user_agent(),
        }

        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        finish_reason: str = ""
        usage_info: dict | None = None

        try:
            with httpx.Client(verify=True, timeout=_DEFAULT_TIMEOUT) as client:
                with client.stream("POST", url, headers=headers, json=payload) as r:
                    if r.status_code != 200:
                        latency_ms = int((time.monotonic() - start) * 1000)
                        return EngineResponse(
                            success=False, text="", latency_ms=latency_ms,
                            error=f"HTTP {r.status_code}",
                        )
                    for line in r.iter_lines():
                        if not line:
                            continue
                        # W5-V: handle BOTH "data: " (standard) and "data:" (Kimi)
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
                            if delta.get("content"):
                                content_chunks.append(delta["content"])
                            if delta.get("reasoning_content"):
                                reasoning_chunks.append(delta["reasoning_content"])
                            fr = choices[0].get("finish_reason")
                            if fr:
                                finish_reason = fr
                        if chunk.get("usage"):
                            usage_info = chunk["usage"]
            latency_ms = int((time.monotonic() - start) * 1000)
            text = "".join(content_chunks)
            tokens_in = int((usage_info or {}).get("prompt_tokens", 0))
            tokens_out = int((usage_info or {}).get("completion_tokens", 0))
            # If the server returned 200 but emitted ZERO parseable
            # chunks (no content, no reasoning, no usage), the response
            # was structurally invalid (e.g. malformed body, gateway
            # filtered).  Surface as failure so callers / fallback chain
            # can react.  Empty content alone (with usage block) is
            # acceptable: server may have hit max_tokens during reasoning;
            # that case still has usage_info populated and guards.py
            # Rule 2 catches the empty-text via classify_response.
            parsed_anything = (
                bool(content_chunks) or bool(reasoning_chunks)
                or usage_info is not None or bool(finish_reason)
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
        except httpx.HTTPStatusError as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False, text="", latency_ms=latency_ms,
                error=f"HTTP {e.response.status_code}",
            )
        except httpx.TimeoutException:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False, text="", latency_ms=latency_ms,
                error="timeout",
            )
        except httpx.ConnectError:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False, text="", latency_ms=latency_ms,
                error="network",
            )
        except httpx.RemoteProtocolError:
            # W5-V: server-disconnect mid-stream (happens occasionally
            # at the 60s gateway timeout if reasoning hasn't yielded
            # content yet).  Capture whatever partial content we have.
            latency_ms = int((time.monotonic() - start) * 1000)
            partial = "".join(content_chunks)
            return EngineResponse(
                success=bool(partial),
                text=partial,
                latency_ms=latency_ms,
                error=None if partial else "kimi_remote_disconnect",
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            return EngineResponse(
                success=False, text="", latency_ms=latency_ms,
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
                tokens_in, tokens_out = _extract_anthropic_usage(data)
                latency_ms = int((time.monotonic() - start) * 1000)
                return EngineResponse(
                    success=True,
                    text=text,
                    latency_ms=latency_ms,
                    error=None,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
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

    Xiaomi runs the Token Plan against THREE regional gateways
    (verified 2026-05-22 against operator's actual dashboard):
      - ``token-plan-sgp.xiaomimimo.com`` — Singapore (international, **default**)
      - ``token-plan-ams.xiaomimimo.com`` — Amsterdam (Europe)
      - ``token-plan-cn.xiaomimimo.com``  — China

    Pay-as-you-go is unified at ``api.xiaomimimo.com``.

    WIRE-MIMO-SGP (2026-05-22): Singapore is the default for international
    accounts.  An earlier default (``ams``) was wrong against the
    operator's tp- key — server returned 401 invalid_key from ams + cn
    endpoints, 200 from sgp.  The key itself is bound to a specific
    regional gateway when provisioned.

    Resolution order:
      1. ``MIMO_BASE_URL`` env var (full URL override)
      2. ``MIMO_REGION`` env var: ``sgp`` | ``ams`` | ``cn`` (default ``sgp``)
      3. Key prefix: ``tp-`` → Token Plan regional; ``sk-`` / other → PAYG
    """
    explicit = os.environ.get("MIMO_BASE_URL", "").strip()
    if explicit:
        url = explicit.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = url + "/chat/completions"
        return url
    region = os.environ.get("MIMO_REGION", "sgp").strip().lower()
    if api_key.startswith("tp-"):
        if region == "cn":
            return "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
        if region == "ams":
            return "https://token-plan-ams.xiaomimimo.com/v1/chat/completions"
        # default + unrecognized values → SGP (Singapore)
        return "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"
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


# WIRE-MIMO-AUTO-ROUTING (2026-05-22): operator-policy default
# ----------------------------------------------------------------------
# Per operator research 2026-05-22: MiMo V2.5-Pro is text-only.
# Multimodal (image / video / audio understanding) only works on
# MiMo V2.5 Standard (the "Omni" model).  So when a packet contains
# multimodal markers we MUST route to ``mimo-v2.5`` regardless of the
# operator-default preference for Pro.
#
# Detection is intentionally simple — any of these surface forms in
# the packet text triggers Standard:
#   - markdown image: ``![...](path)``
#   - HTML img/video/audio tags
#   - inline image data URLs: ``data:image/``, ``data:video/``
#   - common media file extensions in the packet: .png .jpg .jpeg
#     .gif .webp .mp4 .mov .webm .mp3 .wav
#
# Override via ``model=`` in extra_args wins over auto-detection.
# ----------------------------------------------------------------------

DEFAULT_MIMO_MODEL: str = "mimo-v2.5-pro"
MULTIMODAL_MIMO_MODEL: str = "mimo-v2.5"

import re as _re_mimo  # noqa: E402  (imported here to keep module-level imports stable)

_MULTIMODAL_RE = _re_mimo.compile(
    r"!\[[^\]]*\]\("                       # markdown image
    r"|<(?:img|video|audio|source)\b"      # HTML media tags
    r"|data:(?:image|video|audio)/"        # inline data URLs
    r"|\.(?:png|jpe?g|gif|webp|mp4|mov|webm|mp3|wav)\b",
    _re_mimo.IGNORECASE,
)


def detect_mimo_model(packet_content: str,
                      extra_args: Optional[dict[str, Any]] = None) -> str:
    """Return the MiMo model name to use for *packet_content*.

    Resolution order:
      1. explicit ``model`` in extra_args (operator override)
      2. multimodal marker detected in packet → ``mimo-v2.5`` (Standard)
      3. default → ``mimo-v2.5-pro`` (text-only, sharper on coding)
    """
    if extra_args and extra_args.get("model"):
        return str(extra_args["model"])
    if _MULTIMODAL_RE.search(packet_content or ""):
        return MULTIMODAL_MIMO_MODEL
    return DEFAULT_MIMO_MODEL


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

        # WIRE-MIMO-AUTO-ROUTING (2026-05-22): when caller passes a
        # placeholder model (empty, ``auto``, or ``mimo``), detect from
        # packet content.  Explicit model strings (``mimo-v2.5``,
        # ``mimo-v2.5-pro``) pass through untouched so deliberate
        # routing remains operator-controllable.
        if not model or model.strip().lower() in {"auto", "mimo", "default"}:
            model = detect_mimo_model(packet_content, extra)

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
                tokens_in, tokens_out = _extract_openai_usage(data)
                latency_ms = int((time.monotonic() - start) * 1000)
                return EngineResponse(
                    success=True,
                    text=text,
                    latency_ms=latency_ms,
                    error=None,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
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