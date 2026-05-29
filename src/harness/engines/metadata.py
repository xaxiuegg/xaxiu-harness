"""W14-ENGINE-METADATA 2026-05-28: queryable per-engine metadata.

Background
==========

Engine properties (protocol surfaces, key-prefix gates, UA gating,
recommended task classes, latency class) historically lived only in
source-code docstrings + comments + scattered memory entries.  An
agent trying to answer "can MiMo serve OpenAI-shape requests?" or
"is this Kimi key UA-gated?" had to read 100+ lines of source across
multiple files.

This module makes the metadata queryable in 1 call:

    from harness.engines.metadata import describe, compatibility_matrix

    md = describe("mimo-via-claude")
    # md.protocol_surfaces ∈ ("openai", "anthropic")
    # md.key_prefixes      = ("tp-", "sk-", "mp-")
    # md.ua_gating         = "tp-* keys require allowlisted UA"

    matrix = compatibility_matrix()
    # → list of {engine, http_direct, proxy_upstream, pattern_b,
    #            swarm} rows describing consumption paths

The CLI surfaces this via ``harness engines describe <name>`` and
``harness engines compatibility-matrix``.  See
[project_agentic_operator_roadmap_2026_05_28](
~/.claude/projects/D--xaxiu-harness-standalone/memory/...) for the
motivating transcript hiccup (the MiMo conflation that wasted ~30
minutes in a real agent session).

Storage shape
=============

For first-pass simplicity the registry is hardcoded in this module.
A future refactor could pull metadata from an ``@engine_metadata``
decorator on each adapter class.  The dataclass shape is stable so
the move would be additive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class EngineMetadata:
    """Static, inspectable properties of an engine adapter."""

    name: str
    """Engine adapter name, e.g. ``"mimo-via-claude"``,
    ``"deepseek-via-claude"``, ``"kimi-via-claude"``."""

    vendor: str
    """Provider organization: ``"moonshot"``, ``"xiaomi"``,
    ``"deepseek"``, ``"alibaba"``, ``"anthropic"``."""

    description: str
    """One-line human-readable description."""

    protocol_surfaces: Tuple[str, ...]
    """Protocols the provider's API speaks: ``("openai",)`` for
    standard OpenAI-compat, ``("anthropic",)`` for Anthropic-shape,
    ``("openai", "anthropic")`` if BOTH surfaces exist (MiMo is the
    canonical case — surfaced this metadata after the 2026-05-27
    transcript hiccup where an agent read partial source and
    claimed MiMo was Anthropic-only)."""

    default_model: str
    """Default model the engine uses if no override."""

    available_models: Tuple[str, ...] = ()
    """Other models the engine can route to (for ``--model``
    overrides)."""

    key_env: str = ""
    """Primary env var the engine reads for the API key."""

    key_prefixes: Tuple[str, ...] = ()
    """Valid key prefix(es), e.g. ``("sk-",)`` for OpenAI-style or
    ``("tp-", "sk-", "mp-")`` for MiMo (Token Plan / PAYG variants)."""

    ua_gating: str = ""
    """User-Agent allowlist note.  Empty if no UA gating; otherwise
    describes WHICH key types are UA-gated + what to do about it
    (typical mitigation: route through ``harness proxy --upstream
    <name>-via-claude-code`` for TOS-compliant access)."""

    recommended_task_classes: Tuple[str, ...] = ()
    """Task classes (from `harness.engines.routing_recommend`) where
    this engine is the empirical primary or alternate pick."""

    latency_class: str = "unknown"
    """Coarse latency tier: ``"fast"`` (< 15s typical),
    ``"medium"`` (15-40s), ``"slow"`` (> 40s).  Based on the
    W14-MIMO-PRODUCTION-VALIDATION 10-prompt corpus."""

    cost_per_smoke_usd: float = 0.0
    """Per-dispatch cost on a ~40-200 token smoke prompt.  See
    [reference] OPERATOR_GUIDE § 8.2 for the source matrix."""

    consumption_surfaces: Dict[str, str] = field(default_factory=dict)
    """Map of consumption-surface name → support note.  Keys:
    ``"http_direct"`` (talk to the vendor's HTTP API directly),
    ``"proxy_upstream"`` (which ``harness proxy --upstream <name>``
    routes here), ``"pattern_b"`` (which `harness ask --engines X`
    name reaches this), ``"swarm"`` (which xaxiu-swarm backend).
    Values are short strings: ``"yes"``, ``"no"``, or a hint."""

    notes: str = ""
    """Any other gotchas the operator/agent should know — TOS
    issues, model deprecations, etc."""


# ---------------------------------------------------------------------------
# Registry — one entry per supported engine adapter
# ---------------------------------------------------------------------------
#
# Names below match the Pattern B engine names used elsewhere in the
# harness.  The 5 routable engines are kimi-via-claude / mimo-via-
# claude / deepseek-via-claude (Pattern B via Claude Code subprocess)
# plus the "raw" engine names referenced by `xaxiu-swarm` etc.

_ENGINE_METADATA: Dict[str, EngineMetadata] = {
    "mimo-via-claude": EngineMetadata(
        name="mimo-via-claude",
        vendor="xiaomi",
        description=(
            "MiMo (Xiaomi) via Claude Code subprocess.  Pattern B "
            "engine.  Empirically best on default / cost / high-volume / "
            "multimodal task classes (W14-MIMO-PRODUCTION-VALIDATION "
            "2026-05-26)."
        ),
        protocol_surfaces=("openai", "anthropic"),
        default_model="mimo-v2.5-pro",
        available_models=("mimo-v2.5-pro", "mimo-v2.5-flash"),
        key_env="MIMO_API_KEY",
        key_prefixes=("tp-", "sk-", "mp-"),
        ua_gating=(
            "Token Plan keys (tp-* prefix) are User-Agent allowlist-"
            "gated.  Direct httpx is rejected; Claude Code subprocess "
            "carries the allowlisted UA (claude-code/...) — that's why "
            "`harness proxy --upstream mimo-via-claude-code` exists.  "
            "PAYG keys (sk-* / mp-*) bypass the UA gate; you can use "
            "the direct HTTP at /v1/chat/completions with those."
        ),
        recommended_task_classes=(
            "default", "cost", "high-volume", "multimodal",
        ),
        latency_class="medium",
        cost_per_smoke_usd=0.008,
        consumption_surfaces={
            "http_direct": (
                "yes for sk-/mp- (PAYG); UA-blocked for tp- (Token Plan)"
            ),
            "proxy_upstream": "mimo-via-claude-code (subprocess-based)",
            "pattern_b": "mimo-via-claude (Claude Code wrapper)",
            "swarm": "mimo (TOS-compliant via Claude Code subprocess)",
        },
        notes=(
            "MiMo has TWO API surfaces: /v1/chat/completions (OpenAI-"
            "compat) AND /anthropic (Anthropic-compat).  Confusing one "
            "for the other is the canonical W14 hiccup — both exist."
        ),
    ),

    "deepseek-via-claude": EngineMetadata(
        name="deepseek-via-claude",
        vendor="deepseek",
        description=(
            "DeepSeek v4 via Claude Code subprocess.  Pattern B "
            "engine.  Empirically best on latency / audit task classes; "
            "v4-pro override available for max-reasoning audits."
        ),
        protocol_surfaces=("openai",),
        default_model="deepseek-v4-flash",
        available_models=("deepseek-v4-flash", "deepseek-v4-pro"),
        key_env="DEEPSEEK_API_KEY",
        key_prefixes=("sk-",),
        ua_gating="",
        recommended_task_classes=("latency", "audit"),
        latency_class="fast",
        cost_per_smoke_usd=0.015,
        consumption_surfaces={
            "http_direct": "yes (api.deepseek.com/v1/chat/completions)",
            "proxy_upstream": "deepseek-http",
            "pattern_b": "deepseek-via-claude",
            "swarm": "deepseek",
        },
        notes=(
            "v4-flash is the default (cheaper, ~5x lower cost than "
            "v4-pro at comparable quality for non-audit work).  v4-pro "
            "is reserved for ship-blocking audits via the audit task "
            "class."
        ),
    ),

    "kimi-via-claude": EngineMetadata(
        name="kimi-via-claude",
        vendor="moonshot",
        description=(
            "Kimi (Moonshot) via Claude Code subprocess.  Pattern B "
            "engine.  Empirically best on verbose task class (produces "
            "~2.3x more output tokens than peers for equivalent prompts)."
        ),
        protocol_surfaces=("openai", "anthropic"),
        default_model="kimi-for-coding",
        available_models=(
            "kimi-for-coding", "moonshot-v1-8k", "moonshot-v1-32k",
        ),
        key_env="KIMI_API_KEY",
        key_prefixes=("sk-",),
        ua_gating=(
            "Kimi Code subscription tier (api.kimi.com/coding) is UA-"
            "allowlist-gated like MiMo Token Plan.  Direct httpx works "
            "for moonshot-v1 PAYG (api.moonshot.cn) but not the Kimi "
            "Code subscription endpoint.  TOS-compliant route for "
            "subscription tier: `harness proxy --upstream kimi-via-"
            "claude-code`."
        ),
        recommended_task_classes=("verbose",),
        latency_class="slow",
        cost_per_smoke_usd=0.025,
        consumption_surfaces={
            "http_direct": (
                "yes for moonshot-v1 (PAYG); UA-blocked for "
                "kimi-for-coding (subscription)"
            ),
            "proxy_upstream": "kimi-http (PAYG) OR kimi-via-claude-code (subscription)",
            "pattern_b": "kimi-via-claude",
            "swarm": "kimi (CLI agentic), kimi-api (HTTP non-agentic)",
        },
    ),

    "qwen-via-claude": EngineMetadata(
        name="qwen-via-claude",
        vendor="alibaba",
        description=(
            "Qwen 3.6 Plus (Alibaba) via Claude Code subprocess.  "
            "Pattern B-style engine; Apache-2.0 open-weight.  Strategic "
            "plan committed $50/mo PAYG slot for this engine "
            "(coord/CURRENT_PLAN.md)."
        ),
        protocol_surfaces=("openai",),
        default_model="qwen-plus",
        available_models=("qwen-plus", "qwen-turbo", "qwen-max"),
        key_env="DASHSCOPE_API_KEY",
        key_prefixes=("sk-",),
        ua_gating="",
        recommended_task_classes=(),  # not yet wired into recommender
        latency_class="unknown",
        cost_per_smoke_usd=0.0,  # not yet benchmarked
        consumption_surfaces={
            "http_direct": (
                "yes (dashscope.aliyuncs.com/compatible-mode/v1/"
                "chat/completions)"
            ),
            "proxy_upstream": "qwen-http",
            "pattern_b": "not yet wired (requires DASHSCOPE_API_KEY)",
            "swarm": "qwen",
        },
        notes=(
            "Strategic plan replacement for the terminated Kimi slot.  "
            "Apache-2.0 open-weight ⇒ zero TOS termination risk.  "
            "Wiring as a full Pattern B engine is pending key "
            "acquisition (W14-KIMI-REPLACEMENT-WITH-QWEN row in plan)."
        ),
    ),

    "anthropic": EngineMetadata(
        name="anthropic",
        vendor="anthropic",
        description=(
            "Claude (Anthropic) via direct API.  Not part of Pattern B "
            "rotation; used as the in-session driver model.  Optional "
            "fallback if ANTHROPIC_API_KEY is set."
        ),
        protocol_surfaces=("anthropic",),
        default_model="claude-opus-4-7",
        available_models=(
            "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5",
        ),
        key_env="ANTHROPIC_API_KEY",
        key_prefixes=("sk-ant-",),
        ua_gating="",
        recommended_task_classes=(),
        latency_class="medium",
        cost_per_smoke_usd=0.0,  # not benchmarked
        consumption_surfaces={
            "http_direct": "yes (api.anthropic.com/v1/messages)",
            "proxy_upstream": "(not currently registered)",
            "pattern_b": "(N/A — Anthropic IS the Pattern B driver)",
            "swarm": "claude (deprecated for swarm work)",
        },
        notes=(
            "Anthropic is the driver model for the agentic dev manager "
            "operating mode; it should NOT be used as a swarm worker per "
            "[feedback_no_claude_swarm_worker] — sub-agents share blind "
            "spots with the driver."
        ),
    ),

    "claude-via-cc": EngineMetadata(
        name="claude-via-cc",
        vendor="anthropic",
        description=(
            "Claude (Anthropic) via the operator's Claude Code SUBSCRIPTION "
            "(claude login OAuth), run as a Claude Code subprocess — NOT the "
            "pay-per-token API.  Honours an effort knob (Opus 4.8: low|medium"
            "|high|xhigh|max) via the --effort flag."
        ),
        protocol_surfaces=("anthropic",),
        default_model="opus",
        available_models=("opus", "sonnet", "haiku", "claude-opus-4-8"),
        key_env="",  # subscription auth — no env-var key
        key_prefixes=(),
        ua_gating="",
        recommended_task_classes=(),  # explicit-pin only; never auto-routed
        latency_class="medium",
        cost_per_smoke_usd=0.0,  # subscription quota, not metered per-call
        consumption_surfaces={
            "http_direct": "no (subscription OAuth, not an API key)",
            "proxy_upstream": "(not registered)",
            "pattern_b": "claude-via-cc (Claude Code subprocess, subscription)",
            "swarm": "(not wired)",
        },
        notes=(
            "Distinct from the 'anthropic' direct-API engine: that one uses "
            "an sk-ant- key against api.anthropic.com (pay-per-token); this "
            "spawns the local claude binary with NO key so it uses the "
            "operator's subscription.  Requires a prior `claude login`.  "
            "Reachable via `harness ask --engines claude-via-cc [--effort X]` "
            "— bypasses the key-pool since there is no poolable key."
        ),
    ),

    "gemini": EngineMetadata(
        name="gemini",
        vendor="google",
        description=(
            "Gemini (Google) via direct API.  Free tier (15 RPM) is "
            "useful for routine scoring/tailoring workloads.  Not in "
            "the production Pattern B rotation."
        ),
        protocol_surfaces=("openai", "google-genai"),
        default_model="gemini-2.5-pro",
        available_models=("gemini-2.5-pro", "gemini-2.5-flash"),
        key_env="GEMINI_API_KEY",
        key_prefixes=("AIza",),
        ua_gating="",
        recommended_task_classes=(),
        latency_class="fast",
        cost_per_smoke_usd=0.0,  # free tier within RPM cap
        consumption_surfaces={
            "http_direct": (
                "yes (generativelanguage.googleapis.com; OpenAI-compat "
                "endpoint available)"
            ),
            "proxy_upstream": "(not currently registered)",
            "pattern_b": "(not currently wired)",
            "swarm": "(not currently wired)",
        },
        notes=(
            "Free tier 15 RPM is enough for ApplyPilot scoring batches "
            "and other low-volume workloads.  Mentioned here for "
            "completeness; not in the strategic plan's $195/mo budget."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def describe(name: str) -> EngineMetadata:
    """Return metadata for an engine by name.

    Lookup is case-insensitive + accepts both Pattern B names
    (``"mimo-via-claude"``) and swarm/raw names where they coincide.
    Raises ``ValueError`` with a helpful message if not found.
    """
    key = (name or "").strip().lower()
    if key in _ENGINE_METADATA:
        return _ENGINE_METADATA[key]
    raise ValueError(
        f"Unknown engine {name!r}.  Known: "
        f"{', '.join(sorted(_ENGINE_METADATA))}."
    )


def list_engine_metadata() -> Dict[str, EngineMetadata]:
    """Snapshot of all registered engine metadata."""
    return dict(_ENGINE_METADATA)


def compatibility_matrix() -> list:
    """Build the N×M consumption-surface matrix.

    Each row is one engine; each cell describes the support status
    of one consumption surface.  Returned as a list of dicts so the
    CLI can render as text or JSON.

    Surfaces (columns):
      - ``http_direct`` — talk to vendor HTTP API directly
      - ``proxy_upstream`` — via ``harness proxy --upstream <name>``
      - ``pattern_b`` — via ``harness ask --engines <name>``
      - ``swarm`` — via ``xaxiu-swarm dispatch --backend <name>``
    """
    rows = []
    for name in sorted(_ENGINE_METADATA):
        md = _ENGINE_METADATA[name]
        rows.append({
            "engine": name,
            "vendor": md.vendor,
            "protocols": list(md.protocol_surfaces),
            "ua_gated": bool(md.ua_gating),
            "http_direct": md.consumption_surfaces.get("http_direct", "?"),
            "proxy_upstream": md.consumption_surfaces.get(
                "proxy_upstream", "?",
            ),
            "pattern_b": md.consumption_surfaces.get("pattern_b", "?"),
            "swarm": md.consumption_surfaces.get("swarm", "?"),
        })
    return rows
