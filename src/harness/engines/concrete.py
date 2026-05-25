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
from harness.engines.transport import StreamingTransport
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
    """User-Agent for Kimi dispatches.  Default is ``xaxiu-harness/1.0``
    (the truthful client identity) per W14-KIMI-TERMINATION-INVESTIGATION
    2026-05-25.

    Kimi Code's API uses a User-Agent allowlist to gate access to its
    Token Plan endpoint, and the operator's account was terminated on
    2026-05-25 for sending a spoofed ``claude-code/0.1.0`` UA — this
    violates Kimi Code's community guideline #3 (no client-identity
    tampering, "不伪造或篡改客户端身份信息").  Moonshot enforces this;
    see ``coord/reviews/kimi-termination-investigation/FINDINGS.md``.

    Practical consequences of the truthful default:
      - The Kimi Code endpoint (api.kimi.com/coding/v1) will deny our
        traffic at the gate, returning HTTP 403.  That is the CORRECT
        outcome — we are not an approved third-party agent.
      - The Kimi Platform pay-as-you-go endpoint (api.moonshot.ai/v1
        or api.moonshot.cn/v1) does not enforce the UA gate and will
        accept any UA, so PAYG keys still work.

    The ``KIMI_USER_AGENT`` env var still lets an operator override
    to a spoofed value (e.g. ``claude-code/0.1.0`` or ``KimiCLI/1.5``)
    — but the operator must understand this is a TOS violation and
    accept the documented risk of account termination.
    """
    return os.environ.get("KIMI_USER_AGENT", "xaxiu-harness/1.0")


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

class DeepSeekConcrete(StreamingTransport):
    """Concrete engine for DeepSeek chat completions.

    Endpoint: https://api.deepseek.com/v1/chat/completions

    Honoured `extra_args`:
        - ``--no-thinking`` (bool) – force temperature=0.0 and ``thinking: False``.
        - If model name ends with ``-flash`` the same behaviour is applied
          automatically (v1.2 HIGH-7 mitigation for v4-flash packet traps).

    W7-B1-RETROFIT 2026-05-23: refactored to inherit from
    StreamingTransport.  Dispatch loop, SSE parsing, [DONE] terminator,
    chunk aggregation, error mapping all live in the base class.  Only
    the endpoint URL, headers, and payload shape are engine-specific.
    """

    def _endpoint_url(self) -> str:
        return "https://api.deepseek.com/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": _make_user_agent(),
        }

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


class KimiConcrete(StreamingTransport):
    """Concrete engine for Kimi (Moonshot) chat completions.

    Endpoint: https://api.moonshot.cn/v1/chat/completions

    Honoured `extra_args`:
        - ``temperature`` (float) – defaults to 0.6 if not provided.

    W7-B1-RETROFIT 2026-05-23: refactored to inherit from
    StreamingTransport.  Kimi-specific behavior is preserved via three
    overridable hooks:
      - ``_process_delta`` also captures ``reasoning_content``
      - ``_finalize_response`` sets ``reasoning_only`` when content is
        empty but reasoning is present (W7-KIMI-REASONING-EMPTY)
      - ``_handle_remote_protocol_error`` rescues partial content on
        the 60-second mid-stream disconnect (W5-V)

    Three Kimi-specific issues the streaming-first dispatch handles
    (all now in the base class except as noted):

    1. **60-second server wall-clock**: Kimi's gateway closes the
       connection at ~60s on non-stream requests for big packets
       (3KB+ inputs).  Streaming bypasses this.

    2. **Thinking-budget starvation**: kimi-for-coding emits
       ``reasoning_content`` first then ``content``.  Non-stream
       requests with tight max_tokens consume the whole budget on
       reasoning.  Streaming + W7-KIMI-MAX-TOKENS-FLOOR mitigate.

    3. **Non-standard SSE format**: Kimi sends ``data:{...}`` with NO
       space after the colon.  StreamingTransport handles both prefix
       variants (W5-V wiring fix).
    """

    def _endpoint_url(self) -> str:
        return _resolve_kimi_upstream()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            # Kimi Code API enforces a User-Agent allowlist
            "User-Agent": _make_kimi_user_agent(),
        }

    def _process_delta(self, delta: dict, accumulated: dict) -> None:
        """Override the default to also capture ``reasoning_content``.

        Kimi emits reasoning tokens BEFORE user-facing content; we
        keep both so :meth:`_finalize_response` can set
        ``reasoning_only`` (W7-KIMI-REASONING-EMPTY) when reasoning
        exhausts the budget."""
        if delta.get("content"):
            accumulated.setdefault("content_chunks", []).append(
                delta["content"]
            )
        if delta.get("reasoning_content"):
            accumulated.setdefault("reasoning_chunks", []).append(
                delta["reasoning_content"]
            )

    def _finalize_response(
        self,
        accumulated: dict,
        latency_ms: int,
        usage_info: Optional[dict],
        finish_reason: str,
    ) -> EngineResponse:
        content_chunks = accumulated.get("content_chunks", [])
        reasoning_chunks = accumulated.get("reasoning_chunks", [])
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
        # W7-KIMI-REASONING-EMPTY 2026-05-23: detect the case where
        # Kimi spent its entire max_tokens budget on reasoning tokens
        # and emitted ZERO user-facing content.  Surface a distinct
        # reasoning_only=True flag so callers can retry with a larger
        # budget instead of relaying empty text downstream.
        reasoning_only = (
            len(content_chunks) == 0
            and len(reasoning_chunks) > 0
        )
        return EngineResponse(
            success=True, text=text, latency_ms=latency_ms,
            error=None, tokens_in=tokens_in, tokens_out=tokens_out,
            reasoning_only=reasoning_only,
        )

    def _handle_remote_protocol_error(
        self, accumulated: dict, latency_ms: int,
    ) -> Optional[EngineResponse]:
        """W5-V partial-content rescue.

        Server-disconnect mid-stream happens occasionally at the 60s
        gateway timeout when reasoning hasn't yielded content yet.
        Return whatever partial content was already streamed."""
        partial = "".join(accumulated.get("content_chunks", []))
        return EngineResponse(
            success=bool(partial),
            text=partial,
            latency_ms=latency_ms,
            error=None if partial else "kimi_remote_disconnect",
        )

    @staticmethod
    def _build_payload(
        content: str,
        model: str,
        extra: dict[str, Any],
    ) -> dict:
        temperature = extra.get("temperature", 0.6)
        # W5-W 2026-05-23 (operator directive): "do not limit max_tokens
        # of Kimi" — Kimi is unlimited via tp- Token Plan subscription.
        # Default raised from 32K to 200K.  W7-KIMI-MAX-TOKENS-FLOOR
        # 2026-05-23: clamp explicit caller overrides UP to a safety
        # floor so reasoning_content can't exhaust the budget before
        # any user-facing content is emitted.  The W6-PANEL retry hit
        # this when the panel script passed 2_500 and 4_000 — both
        # below the floor, both resulted in success=True text=''.
        # Operators who genuinely need a smaller cap can set
        # extra_args["max_tokens_override_floor"] = True to bypass.
        _KIMI_REASONING_FLOOR = 8_000
        raw_max_tokens = int(extra.get("max_tokens", 200_000))
        if (raw_max_tokens < _KIMI_REASONING_FLOOR
                and not extra.get("max_tokens_override_floor", False)):
            max_tokens = _KIMI_REASONING_FLOOR
        else:
            max_tokens = raw_max_tokens
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

        # W13-ENGINE-RETRY-RESILIENT 2026-05-25: same shared retry
        # helper as MiMo + Gemini.  Auto-retry once on transient httpx
        # errors; preserve repr(exc) for non-transient ones (replaces
        # the prior bare ``except Exception:`` -> "internal").
        from harness.engines._retry import run_with_retry

        def _do_http() -> EngineResponse:
            start = time.monotonic()
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

        return run_with_retry(_do_http)

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
    """User-Agent for MiMo dispatches.  Default is ``xaxiu-harness/1.0``
    (the truthful client identity) per W14-MIMO-TOS-COMPLIANCE 2026-05-25.

    Xiaomi's MiMo Token Plan endpoint (``token-plan-{region}.xiaomimimo.com``)
    is User-Agent gated to an allowlist of approved coding tools:
    OpenCode, OpenClaw, Claude Code, Cherry Studio, Cline, Qwen Code,
    CodeBuddy, Kilo Code, Hermes Agent.  xaxiu-harness is NOT on that
    list.  The Token Plan subscription page also explicitly prohibits
    use outside approved programming tools:
    "The Token Plan package quota can only be used in programming tools
    (such as OpenClaw, OpenCode, etc.), and it is prohibited to use it
    in the form of API calls for request behaviors in clearly non-Coding
    scenarios such as automated scripts and custom application backends."

    Enforcement (verbatim from MiMo TOS):
    "If an API Key corresponding to a package is used for calls that
    exceed the permitted scope, it will be considered a violation or
    abuse, and the platform has the right to take measures such as
    suspending service and banning the API Key."

    Kimi Code already terminated the operator's account for the prior
    ``claude-code/0.1.0`` spoofing default; Xiaomi could follow with the
    same enforcement, so we switch to the truthful UA pre-emptively.

    Practical consequences of the truthful default:
      - Token Plan (tp- keys, regional endpoint) will deny our traffic
        at the gate.  That is the CORRECT outcome — we are not an
        approved third-party agent.
      - Pay-as-you-go (sk- keys, ``api.xiaomimimo.com``) does not
        enforce the UA gate and continues to work.

    The ``MIMO_USER_AGENT`` env var still lets an operator override
    to a spoofed value (e.g. ``claude-code/0.1.0``) — but the operator
    must understand this is a TOS violation and accept the documented
    risk of account termination.
    """
    return os.environ.get("MIMO_USER_AGENT", "xaxiu-harness/1.0")


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

        # W13-ENGINE-RETRY-RESILIENT 2026-05-25: wrap the HTTP work in
        # the shared retry helper.  Previously a bare ``except Exception:``
        # masked transient RemoteProtocolError events as the opaque
        # string "internal" — the W13 investigation showed 12/12
        # retries of those "failures" succeeded.  The helper auto-
        # retries once on transient httpx errors + preserves repr(exc)
        # in the error field for non-transient ones.
        from harness.engines._retry import run_with_retry

        def _do_http() -> EngineResponse:
            start = time.monotonic()
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

        return run_with_retry(_do_http)

    @staticmethod
    def _build_payload(
        content: str,
        model: str,
        extra: dict[str, Any],
    ) -> dict:
        temperature = float(extra.get("temperature", 0.6))
        # W5-W 2026-05-23 (operator directive): "do not limit max_tokens
        # of unlimited-subscription engines" — MiMo via tp- Token Plan
        # is flat-rate.  Default raised to MiMo's hardware max (131072).
        # sk- pay-per-token callers can override via extra_args if cost
        # control is needed.
        max_tokens = int(extra.get("max_tokens", 131_072))
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
    # W11-DPAPI-CROSS-PLATFORM 2026-05-25: route through the central
    # resolver so .env files work on Linux/Mac agents.  Pre-W11 the
    # only paths were os.environ + DPAPI (Windows-only), which broke
    # any non-Windows agentic-coding-agent use.  Now: env > .env >
    # DPAPI fallback, with prefer_dpapi=True still respected for
    # legacy Windows-operator flow.
    from harness.secrets.resolve import resolve_key
    api_key = resolve_key(env_var, prefer_dpapi=prefer_dpapi)

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