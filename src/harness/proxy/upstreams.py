"""W14-PROXY-UPSTREAMS 2026-05-27: registry of proxy upstreams.

The proxy's pre-v0.5.1 form was hardcoded to forward HTTP requests to
``api.moonshot.cn`` (Kimi).  This module generalizes the upstream as a
queryable registry covering BOTH:

- HTTP-direct upstreams (kimi, deepseek, qwen — forward via httpx)
- Claude-Code-subprocess upstreams (mimo, kimi — spawn ``claude --bare``
  with the right ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN env vars,
  parse the resulting JSON, translate back to OpenAI shape)

Why subprocess for some upstreams
=================================

MiMo Token Plan SGP and Kimi Code gate client identity via User-Agent
allowlist.  Direct httpx (User-Agent ``python-httpx/...``) gets
rejected.  The ``claude`` binary IS on both providers' allowlists
(legitimate UA ``claude-code/...``), so wrapping its subprocess as an
HTTP server gives third-party tools an OpenAI-compatible endpoint
backed by a TOS-compliant client.

This is the pattern an agent in a 2026-05-27 session hand-rolled as
a standalone FastAPI shim (~80 LOC) when working around the harness's
HTTP-only proxy.  Folding the pattern into the harness eliminates that
class of one-off shim entirely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class UpstreamSpec:
    """One upstream the proxy can route requests to.

    The ``transport`` field is the load-bearing distinction:
    ``"http"`` uses the existing HTTP-forward path; ``"claude-code-
    subprocess"`` spawns the ``claude`` binary per request with the
    upstream's environment overrides.
    """
    name: str
    """Stable identifier used in ``--upstream <name>``."""

    transport: str
    """``"http"`` or ``"claude-code-subprocess"``."""

    key_env: str
    """Env-var prefix the proxy looks up keys under (e.g.
    ``"KIMI_API_KEY"`` → also reads ``KIMI_API_KEY_1`` etc)."""

    base_url: str
    """For HTTP transport: the upstream chat-completions URL.
    For subprocess transport: the ``ANTHROPIC_BASE_URL`` value."""

    default_model: str
    """Model name the subprocess transport passes to ``claude --model``
    (and the OpenAI-shape response advertises in its ``model`` field)."""

    description: str = ""
    """One-line operator-facing description."""

    env_overrides: Dict[str, str] = field(default_factory=dict)
    """Extra env vars to set on the subprocess (subprocess transport
    only).  ``ANTHROPIC_AUTH_TOKEN`` and ``ANTHROPIC_API_KEY`` are
    auto-set from the resolved API key; this is for upstream-specific
    extras like ``ANTHROPIC_DEFAULT_OPUS_MODEL`` pinning."""

    tos_notes: str = ""
    """Operator-facing notes on TOS compliance / allowlist gating
    (e.g. why a subprocess upstream exists at all)."""


# ---------------------------------------------------------------------------
# Registry — one entry per supported upstream
# ---------------------------------------------------------------------------

_UPSTREAMS: Dict[str, UpstreamSpec] = {
    "kimi-http": UpstreamSpec(
        name="kimi-http",
        transport="http",
        key_env="KIMI_API_KEY",
        base_url="https://api.moonshot.cn/v1/chat/completions",
        default_model="moonshot-v1-8k",
        description="Kimi (Moonshot) via direct HTTP.  The pre-v0.5.1 "
                    "proxy default.",
    ),
    "deepseek-http": UpstreamSpec(
        name="deepseek-http",
        transport="http",
        key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/v1/chat/completions",
        default_model="deepseek-chat",
        description="DeepSeek v4 via direct HTTP.  PAYG, OpenAI-compat.",
    ),
    "qwen-http": UpstreamSpec(
        name="qwen-http",
        transport="http",
        key_env="DASHSCOPE_API_KEY",
        base_url=(
            "https://dashscope.aliyuncs.com/compatible-mode/"
            "v1/chat/completions"
        ),
        default_model="qwen-plus",
        description="Qwen 3.6 Plus via Alibaba DashScope (OpenAI-compat "
                    "mode).  PAYG.",
    ),
    "mimo-via-claude-code": UpstreamSpec(
        name="mimo-via-claude-code",
        transport="claude-code-subprocess",
        key_env="MIMO_API_KEY",
        base_url="https://token-plan-sgp.xiaomimimo.com/anthropic",
        default_model="mimo-v2.5-pro",
        description="MiMo Token Plan SGP via Claude Code subprocess.  "
                    "TOS-compliant for tp-* keys (UA-gated provider).",
        env_overrides={
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "mimo-v2.5-pro",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "mimo-v2.5-pro",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "mimo-v2.5-pro",
            "CLAUDE_CODE_SUBAGENT_MODEL": "mimo-v2.5-pro",
            "ENABLE_TOOL_SEARCH": "false",
        },
        tos_notes="MiMo Token Plan keys (tp-* prefix) are User-Agent "
                  "gated — direct httpx is rejected.  Routing through "
                  "the claude binary (allowlisted UA claude-code/...) "
                  "is TOS-compliant.  PAYG keys (sk-* / mp-*) bypass "
                  "the UA gate and can use a direct HTTP upstream "
                  "instead.",
    ),
    "kimi-via-claude-code": UpstreamSpec(
        name="kimi-via-claude-code",
        transport="claude-code-subprocess",
        key_env="KIMI_API_KEY",
        base_url="https://api.kimi.com/coding",
        default_model="kimi-for-coding",
        description="Kimi Code (K2.6) via Claude Code subprocess.  "
                    "TOS-compliant alternative when direct HTTP fails "
                    "auth.",
        env_overrides={
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "kimi-for-coding",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "kimi-for-coding",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "kimi-for-coding",
            "CLAUDE_CODE_SUBAGENT_MODEL": "kimi-for-coding",
            "ENABLE_TOOL_SEARCH": "false",
        },
        tos_notes="Kimi Code subscription tier uses the same UA-gating "
                  "pattern as MiMo TP.  The claude binary carries the "
                  "allowlisted UA.",
    ),
}


def get_upstream(name: str) -> UpstreamSpec:
    """Look up a registered upstream by name.

    Raises ``ValueError`` with a helpful message listing valid names
    if the lookup fails.  Case-insensitive.
    """
    key = (name or "").strip().lower()
    if key in _UPSTREAMS:
        return _UPSTREAMS[key]
    raise ValueError(
        f"Unknown upstream {name!r}.  Valid: "
        f"{', '.join(sorted(_UPSTREAMS))}."
    )


def list_upstreams() -> Dict[str, UpstreamSpec]:
    """Return a snapshot of all registered upstreams."""
    return dict(_UPSTREAMS)


# Default upstream when none specified — preserves pre-v0.5.1 behavior.
DEFAULT_UPSTREAM_NAME = "kimi-http"
