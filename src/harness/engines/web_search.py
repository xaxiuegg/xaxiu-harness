"""W14-WEB-SEARCH-TIER1 2026-05-29: Pattern A ``/v1`` web-search dispatch.

The 2026-05-29 Kimi + MiMo documentation review (every doc page) plus live
probes established the decisive fact for the cross-vendor pivot:

    Provider web search lives on the OpenAI-compatible ``/v1`` endpoint,
    NOT the ``/anthropic`` endpoint that the ``*-via-claude`` Pattern B
    engines drive.  (MiMo states verbatim: "Anthropic API is not currently
    supported" for web search.)

So web search is reached by talking the providers' native ``/v1`` chat-
completions protocol directly (Pattern A) and running the tool loop here.
There are two provider-specific shapes -- this module handles both:

MiMo
    ``{"type":"web_search", "max_keyword":N, "force_search":bool,
    "limit":N, "user_location":{...}}`` in the ``tools`` array.  Executed
    SERVER-SIDE; results come back INLINE as ``message.annotations``
    (``url_citation`` objects).  Single request -- no client round-trip.

    PREREQUISITE (verified live 2026-05-29): the **Web Search Plugin must
    be enabled in the MiMo console** -- Console -> Plugin Management
    (https://platform.xiaomimimo.com/#/console/plugin).  Until then the API
    returns HTTP 400 ``"web search tool found in the request body, but
    webSearchEnabled is false"``.  There is a ~5-minute cache after toggling.

Kimi
    ``{"type":"builtin_function", "function":{"name":"$web_search"}}``.  The
    model returns ``finish_reason=tool_calls``; the CLIENT echoes
    ``tool_call.function.arguments`` back UNCHANGED in a ``role=tool``
    message; Kimi then executes the search server-side and returns the
    grounded answer.  ``thinking`` must be DISABLED.  Lives on the Kimi
    **Open Platform** endpoint (``https://api.moonshot.ai/v1``) -- NOT the
    Code-subscription endpoint and NOT the local proxy.  ~$0.005/call.

Both functions return an :class:`EngineResponse`.  Citations are folded into
``text`` as a trailing "Sources:" block so the frozen EngineResponse schema
is unchanged.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import httpx

from harness.engines.base import EngineResponse

KIMI_OPEN_PLATFORM_ENDPOINT = "https://api.moonshot.ai/v1/chat/completions"
MIMO_CONSOLE_PLUGIN_URL = "https://platform.xiaomimimo.com/#/console/plugin"


def _fold_citations(text: str, citations: list[dict]) -> str:
    """Append a 'Sources:' block to *text* from a list of citation dicts."""
    lines: list[str] = []
    for c in citations:
        if not isinstance(c, dict):
            continue
        url = c.get("url") or ""
        if not url:
            continue
        title = (c.get("title") or c.get("site_name") or "").strip()
        lines.append(f"- {title} {url}".strip())
    if not lines:
        return text
    return f"{text.rstrip()}\n\nSources:\n" + "\n".join(lines)


def mimo_web_search(
    query: str,
    *,
    api_key: str,
    model: str = "mimo-v2.5-pro",
    endpoint: Optional[str] = None,
    force_search: bool = True,
    max_keyword: int = 3,
    limit: int = 5,
    user_location: Optional[dict] = None,
    max_tokens: int = 4000,
    timeout: float = 150.0,
) -> EngineResponse:
    """MiMo web search (server-side, inline annotations -- no round-trip).

    Verified request shape (2026-05-29 live probe).  Gated by the MiMo
    console Web Search Plugin toggle; on a 400 ``webSearchEnabled is false``
    the error string carries the actionable enable-it hint.
    """
    from harness.engines.concrete import (
        _extract_chat_text,
        _extract_openai_usage,
        _make_mimo_user_agent,
        _resolve_mimo_upstream,
    )

    url = endpoint or _resolve_mimo_upstream(api_key)
    tool: dict[str, Any] = {
        "type": "web_search",
        "max_keyword": int(max_keyword),
        "force_search": bool(force_search),
        "limit": int(limit),
    }
    if user_location:
        tool["user_location"] = user_location
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": query}],
        "tools": [tool],
        "max_tokens": int(max_tokens),
    }
    start = time.monotonic()
    try:
        with httpx.Client(verify=True, timeout=timeout) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": _make_mimo_user_agent(),
                },
                json=payload,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            try:
                data = resp.json()
            except Exception:
                return EngineResponse(
                    success=False, text="", latency_ms=latency_ms,
                    error=f"mimo_web_search: HTTP {resp.status_code} "
                          f"(non-JSON body)",
                )
            if resp.status_code != 200 or "error" in data:
                err = data.get("error", {}) if isinstance(data, dict) else {}
                msg = (err.get("message") or err.get("param")
                       or f"HTTP {resp.status_code}")
                if "websearchenabled" in json.dumps(err).lower():
                    msg = (f"{msg} -- enable the Web Search Plugin at "
                           f"{MIMO_CONSOLE_PLUGIN_URL} (≈5-min cache)")
                return EngineResponse(
                    success=False, text="", latency_ms=latency_ms,
                    error=f"mimo_web_search: {msg}",
                )
            text = _extract_chat_text(data)
            tokens_in, tokens_out = _extract_openai_usage(data)
            message = (data.get("choices") or [{}])[0].get("message", {})
            citations = message.get("annotations") or []
            return EngineResponse(
                success=True,
                text=_fold_citations(text, citations),
                latency_ms=latency_ms,
                error=None,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
    except Exception as exc:  # noqa: BLE001 - surface as failure, never raise
        return EngineResponse(
            success=False, text="",
            latency_ms=int((time.monotonic() - start) * 1000),
            error=f"mimo_web_search: {type(exc).__name__}: {exc}",
        )


def kimi_web_search(
    query: str,
    *,
    api_key: str,
    model: str = "kimi-k2.6",
    endpoint: str = KIMI_OPEN_PLATFORM_ENDPOINT,
    max_tokens: int = 4000,
    timeout: float = 150.0,
    max_rounds: int = 4,
) -> EngineResponse:
    """Kimi ``$web_search`` builtin_function with the client round-trip.

    The model emits ``finish_reason=tool_calls``; we echo the args back
    unchanged in a ``role=tool`` message and re-send; Kimi runs the search
    and returns the grounded answer.  ``thinking`` disabled (required by
    ``$web_search``).  Targets the Open Platform endpoint by default.

    NOTE: the request shape is doc-grounded but NOT yet live-verified end to
    end (the harness Kimi engine routes through the local proxy + a stale
    key, so a clean Open-Platform probe is pending an Open-Platform key).
    """
    from harness.engines.concrete import (
        _extract_openai_usage,
        _make_kimi_user_agent,
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": query}]
    tools = [{"type": "builtin_function", "function": {"name": "$web_search"}}]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": _make_kimi_user_agent(),
    }
    start = time.monotonic()
    tokens_in_total = tokens_out_total = 0
    try:
        with httpx.Client(verify=True, timeout=timeout) as client:
            for _ in range(max_rounds):
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "thinking": {"type": "disabled"},
                    "max_tokens": int(max_tokens),
                }
                resp = client.post(endpoint, headers=headers, json=payload)
                try:
                    data = resp.json()
                except Exception:
                    return EngineResponse(
                        success=False, text="",
                        latency_ms=int((time.monotonic() - start) * 1000),
                        error=f"kimi_web_search: HTTP {resp.status_code} "
                              f"(non-JSON body)",
                    )
                if resp.status_code != 200 or "error" in data:
                    err = data.get("error", {}) if isinstance(data, dict) else {}
                    m = (err.get("message") if isinstance(err, dict)
                         else str(err)) or f"HTTP {resp.status_code}"
                    return EngineResponse(
                        success=False, text="",
                        latency_ms=int((time.monotonic() - start) * 1000),
                        error=f"kimi_web_search: {m}",
                    )
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message", {})
                t_in, t_out = _extract_openai_usage(data)
                tokens_in_total += t_in
                tokens_out_total += t_out
                tool_calls = message.get("tool_calls") or []
                if choice.get("finish_reason") == "tool_calls" and tool_calls:
                    # Echo $web_search args back unchanged; Kimi executes.
                    messages.append({
                        "role": "assistant",
                        "content": message.get("content") or "",
                        "tool_calls": tool_calls,
                    })
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "name": fn.get("name"),
                            "content": fn.get("arguments", ""),
                        })
                    continue
                return EngineResponse(
                    success=True,
                    text=message.get("content") or "",
                    latency_ms=int((time.monotonic() - start) * 1000),
                    error=None,
                    tokens_in=tokens_in_total,
                    tokens_out=tokens_out_total,
                )
            return EngineResponse(
                success=False, text="",
                latency_ms=int((time.monotonic() - start) * 1000),
                error=f"kimi_web_search: exceeded max_rounds={max_rounds} "
                      f"without a final answer",
            )
    except Exception as exc:  # noqa: BLE001
        return EngineResponse(
            success=False, text="",
            latency_ms=int((time.monotonic() - start) * 1000),
            error=f"kimi_web_search: {type(exc).__name__}: {exc}",
        )
