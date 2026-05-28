"""W14-PROXY-UPSTREAMS 2026-05-27: per-transport request handlers.

The proxy delegates each ``/v1/chat/completions`` request to one of:

- ``http_handler`` — forward verbatim to the upstream's HTTP endpoint
  with an ``Authorization: Bearer <key>`` header.  Pre-v0.5.1 behavior.
- ``claude_code_subprocess_handler`` — translate OpenAI request →
  spawn ``claude --bare`` with the upstream's env overrides + the
  resolved key → parse Claude's JSON → translate back to OpenAI shape.

Subprocess pattern is TOS-compliant for User-Agent-gated providers
(MiMo Token Plan SGP, Kimi Code).  The translation logic is cribbed
from a working hand-rolled shim built during a 2026-05-27 agent
session (~80 LOC); folded into the harness so future agents don't
reinvent it.

Latency note: subprocess upstreams pay ~5-7s of Claude-Code boot per
request on top of the actual LLM call.  This is unavoidable on
TOS-compliant routes — direct HTTP would be ~100ms overhead but
breaks the provider's TOS.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration — resolved lazily so module import doesn't fail when
# the claude binary isn't on PATH.
# ---------------------------------------------------------------------------

def _resolve_claude_binary() -> str:
    """Find the ``claude`` binary or raise with a clear error.

    Resolution order:
      1. ``HARNESS_CLAUDE_CODE_BINARY`` env var (operator override)
      2. ``shutil.which("claude")`` — PATH lookup
      3. Common Windows location ``~/.local/bin/claude.exe``
    """
    candidate = os.environ.get("HARNESS_CLAUDE_CODE_BINARY", "").strip()
    if candidate and (
        os.path.exists(candidate) or shutil.which(candidate)
    ):
        return candidate
    found = shutil.which("claude")
    if found:
        return found
    win_path = os.path.expanduser(r"~\.local\bin\claude.exe")
    if os.path.exists(win_path):
        return win_path
    raise FileNotFoundError(
        "claude binary not found.  Install Claude Code CLI from "
        "https://docs.claude.com/en/docs/claude-code/setup or set "
        "HARNESS_CLAUDE_CODE_BINARY=<absolute path>."
    )


# Default subprocess timeout (per-request).  Subprocess upstreams are
# slow by design (Claude Code boot + actual API call); 300s is the
# upper bound the shim used.
DEFAULT_SUBPROCESS_TIMEOUT_S = 300

# Default per-request budget cap for the subprocess (passed to
# ``claude --max-budget-usd``).
DEFAULT_SUBPROCESS_MAX_BUDGET_USD = 5.0


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------

async def http_handler(
    upstream,  # UpstreamSpec
    request_body: bytes,
    api_key: str,
    http_client,  # httpx.AsyncClient
) -> tuple[bytes, int]:
    """Forward request to an HTTP upstream with Bearer auth.

    Returns ``(response_body, status_code)``.  Caller wraps in a
    FastAPI ``Response``.

    Failure modes propagate as exceptions for the caller's circuit-
    breaker logic to classify.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    resp = await http_client.post(
        upstream.base_url, headers=headers, content=request_body,
    )
    return resp.content, resp.status_code


# ---------------------------------------------------------------------------
# Claude-Code subprocess transport (TOS-compliant for UA-gated providers)
# ---------------------------------------------------------------------------

def _extract_text(content: Any) -> str:
    """Pull plain text out of either a string or an OpenAI-style
    list-of-parts content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content or "")


def messages_to_prompts(messages: list[dict]) -> tuple[str, str]:
    """Convert an OpenAI messages array into ``(system, user_text)``.

    System messages are concatenated.  User and assistant messages are
    serialized as ``User:`` / ``Assistant:`` prefixed turns, except for
    the trivial single-user-message case (no assistant turns) where the
    user content is sent verbatim so single-shot prompts feel natural.
    """
    system_parts: list[str] = []
    convo_parts: list[str] = []
    has_assistant = any(m.get("role") == "assistant" for m in messages)
    user_count = 0
    for m in messages:
        role = m.get("role", "")
        text = _extract_text(m.get("content", ""))
        if role == "system":
            system_parts.append(text)
        elif role == "user":
            user_count += 1
            if user_count == 1 and not has_assistant:
                convo_parts.append(text)
            else:
                convo_parts.append(f"User: {text}")
        elif role == "assistant":
            convo_parts.append(f"Assistant: {text}")
    return (
        "\n\n".join(p for p in system_parts if p),
        "\n\n".join(p for p in convo_parts if p),
    )


def _build_subprocess_env(upstream, api_key: str) -> dict[str, str]:
    """Build the env dict for ``claude --bare``.

    Inherits the parent process env then layers upstream-specific
    overrides on top.  ``ANTHROPIC_AUTH_TOKEN`` + ``ANTHROPIC_API_KEY``
    are set from ``api_key`` regardless of what ``env_overrides``
    says (the key is dynamic; the model pins are static).
    """
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = upstream.base_url
    env["ANTHROPIC_AUTH_TOKEN"] = api_key
    env["ANTHROPIC_API_KEY"] = api_key
    env["ANTHROPIC_MODEL"] = upstream.default_model
    for k, v in (upstream.env_overrides or {}).items():
        env[k] = v
    return env


def run_claude_subprocess(
    upstream,
    system: str,
    user_text: str,
    api_key: str,
    *,
    timeout_s: int = DEFAULT_SUBPROCESS_TIMEOUT_S,
    max_budget_usd: float = DEFAULT_SUBPROCESS_MAX_BUDGET_USD,
    claude_binary: Optional[str] = None,
    _run: Optional[Any] = None,
) -> dict[str, Any]:
    """Spawn ``claude --bare --print --output-format json`` once.

    Returns the parsed Claude JSON dict.  Raises ``RuntimeError`` on
    non-zero exit, ``subprocess.TimeoutExpired`` on timeout, or
    ``json.JSONDecodeError`` if the output is unparseable.

    ``_run`` is a test seam — if provided, called instead of
    ``subprocess.run``.  Signature must match ``subprocess.run``.
    """
    binary = claude_binary or _resolve_claude_binary()
    runner = _run or subprocess.run

    cmd = [
        binary,
        "--bare",
        "--print",
        "--output-format", "json",
        "--model", upstream.default_model,
        "--max-budget-usd", str(max_budget_usd),
        "--permission-mode", "bypassPermissions",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--tools", "",
    ]
    if system:
        cmd.extend(["--system-prompt", system])

    proc = runner(
        cmd,
        input=user_text,
        env=_build_subprocess_env(upstream, api_key),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude --bare exit {proc.returncode}: "
            f"stderr={(proc.stderr or '')[:500]!r}"
        )

    raw = proc.stdout or ""
    brace = raw.find("{")
    if brace == -1:
        raise RuntimeError(
            f"claude --bare returned no JSON: stdout={raw[:500]!r}"
        )
    result = json.loads(raw[brace:])
    if result.get("is_error"):
        raise RuntimeError(
            f"claude --bare reported error: "
            f"{result.get('error') or result}"
        )
    return result


def claude_json_to_openai_response(
    claude_json: dict, model: str,
) -> dict:
    """Translate Claude --bare JSON output into an OpenAI ChatCompletion
    response dict."""
    text = claude_json.get("result", "") or ""
    usage = claude_json.get("usage", {}) or {}
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    stop_reason = claude_json.get("stop_reason", "end_turn")
    finish_map = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }
    finish = finish_map.get(stop_reason, "stop")
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": finish,
        }],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


async def claude_code_subprocess_handler(
    upstream,
    request_body: bytes,
    api_key: str,
    http_client=None,  # unused; kept for handler-signature symmetry
    *,
    timeout_s: int = DEFAULT_SUBPROCESS_TIMEOUT_S,
    max_budget_usd: float = DEFAULT_SUBPROCESS_MAX_BUDGET_USD,
    _runner: Optional[Any] = None,
) -> tuple[bytes, int]:
    """Run an OpenAI-shape request through ``claude --bare`` and
    translate the response back to OpenAI shape.

    The subprocess call is blocking; we offload to the default thread-
    pool executor so the FastAPI event loop stays responsive.
    """
    try:
        body = json.loads(request_body)
    except json.JSONDecodeError as e:
        err = json.dumps({"error": f"invalid JSON body: {e}"}).encode()
        return err, 400

    messages = body.get("messages") or []
    if not messages:
        err = json.dumps({"error": "messages array is required"}).encode()
        return err, 400

    system, user_text = messages_to_prompts(messages)
    if not user_text:
        err = json.dumps({
            "error": "no user/assistant content extracted from messages",
        }).encode()
        return err, 400

    loop = asyncio.get_event_loop()
    try:
        claude_json = await loop.run_in_executor(
            None,
            lambda: run_claude_subprocess(
                upstream, system, user_text, api_key,
                timeout_s=timeout_s, max_budget_usd=max_budget_usd,
                _run=_runner,
            ),
        )
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError, FileNotFoundError) as e:
        # 502 mirrors the HTTP upstream's failure semantics so the
        # circuit breaker classifies subprocess failures the same way.
        err = json.dumps({
            "error": f"{type(e).__name__}: {e}",
            "upstream": upstream.name,
            "transport": "claude-code-subprocess",
        }).encode()
        return err, 502

    openai_resp = claude_json_to_openai_response(
        claude_json, upstream.default_model,
    )
    return json.dumps(openai_resp).encode(), 200


# ---------------------------------------------------------------------------
# Dispatcher — pick the right handler for an upstream
# ---------------------------------------------------------------------------

async def dispatch_to_upstream(
    upstream,
    request_body: bytes,
    api_key: str,
    http_client,
) -> tuple[bytes, int]:
    """Route to the appropriate handler based on ``upstream.transport``.

    Single entry-point used by ``app.py``'s ``/v1/chat/completions``
    handler.  Adding a new transport = adding a branch here.
    """
    if upstream.transport == "http":
        return await http_handler(
            upstream, request_body, api_key, http_client,
        )
    if upstream.transport == "claude-code-subprocess":
        return await claude_code_subprocess_handler(
            upstream, request_body, api_key, http_client,
        )
    raise ValueError(
        f"Unsupported transport {upstream.transport!r} for upstream "
        f"{upstream.name!r}.  Supported: http, claude-code-subprocess."
    )
