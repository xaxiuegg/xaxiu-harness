"""W14-CROSS-ENGINE-AUDIT 2026-05-26: programmatic routing recommendations.

Single source of truth for the empirical routing rules documented in
``spec/engine-routing-empirical.md``.  Used by ``harness engines
recommend <task-class>`` and importable by any caller that wants
data-driven engine selection.

Task classes
============

  - ``default``     — routine code / reasoning / debugging
  - ``latency``     — speed-critical (panel work, ≤ 15s budget)
  - ``verbose``     — detailed elaboration / writeups
  - ``cost``        — high-volume / cost-sensitive
  - ``multimodal``  — prompts with image markdown refs
  - ``audit``       — ship-critical cross-engine verification step

The recommendation is the engine name (``"mimo-via-claude"``, etc.)
that the smoke matrix says performs best for that class.  For the
``audit`` class the caller must pass the engine that produced the
prior result so we can return a DIFFERENT engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


VALID_TASK_CLASSES: frozenset[str] = frozenset({
    "default",
    "latency",
    "verbose",
    "cost",
    "high-volume",
    "multimodal",
    "audit",
})


@dataclass(frozen=True)
class Recommendation:
    """A routing recommendation: primary + alternates + rationale."""
    engine: str
    alternates: tuple[str, ...]
    rationale: str
    model_override: Optional[str] = None


# Latency rankings observed in the W14-CROSS-ENGINE-AUDIT smoke matrix
# (2026-05-26, 5-category × 3-engine, all-green after W14 fixes):
#
#   mimo-via-claude     —  9.3s avg, 596 tokens out
#   deepseek-via-claude — 10.0s avg, 608 tokens out  (w/ v4-flash default)
#   kimi-via-claude     — 17.9s avg, 1406 tokens out
#
# These rankings shift with provider load.  Recommendations encode
# them as a STARTING preference; runtime health (W14-KEYS-POOL-TIER2)
# can further filter.


def recommend(
    task_class: str,
    *,
    exclude: Optional[set[str]] = None,
) -> Recommendation:
    """Return a routing recommendation for ``task_class``.

    Parameters
    ----------
    task_class
        One of ``VALID_TASK_CLASSES``.  Unknown values fall back to
        ``"default"``.
    exclude
        Engine names to skip — for the ``audit`` class, pass the
        first-pass engine so we pick a DIFFERENT one for the audit.
        Also useful for "this engine is quarantined" cases.

    Returns
    -------
    Recommendation
        Primary engine + ranked alternates + free-text rationale +
        optional model_override (for ``audit`` we override DeepSeek
        to v4-pro for max-reasoning).
    """
    tc = (task_class or "").strip().lower()
    if tc not in VALID_TASK_CLASSES:
        tc = "default"
    excluded = exclude or set()

    if tc == "default":
        # W14-MIMO-PRODUCTION-VALIDATION 2026-05-26: on 10-prompt
        # realistic corpus, MiMo scored 100% (31/31 checks) vs
        # DeepSeek-flash 97% and Kimi 97%.  MiMo is also the
        # cheapest.  The latency tradeoff (36.8s vs 10.2s) is
        # accepted at default because most "default" callers value
        # correctness + cost over latency; latency-critical
        # callers should use the latency task class explicitly.
        primary = "mimo-via-claude"
        alternates = ("deepseek-via-claude", "kimi-via-claude")
        rationale = (
            "MiMo-via-claude scored 100% (31/31 programmatic checks) "
            "on a 10-prompt production corpus + is the cheapest of "
            "the three.  Latency is 36.8s vs DeepSeek's 10.2s - "
            "if you need speed pick the `latency` task class "
            "instead (returns DeepSeek-flash)."
        )
    elif tc == "latency":
        # W14-MIMO-PRODUCTION-VALIDATION 2026-05-26 RECALIBRATION:
        # smoke-matrix data showed MiMo at 9.3s, but that was on
        # trivial prompts (100-200 token outputs).  On realistic
        # production-class prompts (50-300 word outputs across 10
        # category corpus), MiMo averaged 36.8s and was SLOWEST on
        # every single category.  DeepSeek-flash averaged 10.2s
        # and won latency on every prompt.  Flipping primary from
        # MiMo to DeepSeek-flash to match production reality.
        primary = "deepseek-via-claude"
        alternates = ("mimo-via-claude",)
        rationale = (
            "DeepSeek-flash at 10.2s avg on 10-prompt production "
            "corpus (W14-MIMO-PRODUCTION-VALIDATION).  Fastest on "
            "every category.  MiMo averaged 36.8s on same corpus "
            "- the smoke matrix's 9.3s was trivial-prompt only and "
            "did not extrapolate to realistic workloads.  Kimi "
            "averages 39.0s.  Use DeepSeek-flash when latency "
            "matters."
        )
    elif tc == "verbose":
        primary = "kimi-via-claude"
        alternates = ("deepseek-via-claude",)
        rationale = (
            "Kimi produces 2.3× more output tokens than the other "
            "two for equivalent prompts; right when elaboration IS "
            "the deliverable.  Accept the 18-50s latency."
        )
    elif tc == "cost":
        # W14-MIMO-PRICE-CUT 2026-05-26 6PM PDT + W14-MIMO-PRODUCTION-
        # VALIDATION evening: MiMo is cheapest on BOTH the smoke
        # matrix ($0.033) AND the production corpus ($0.088 for 10
        # realistic prompts vs DeepSeek $0.111 and Kimi $0.245).
        # Plus highest quality score (100% vs 97%).
        primary = "mimo-via-claude"
        alternates = ("kimi-via-claude", "deepseek-via-claude")
        rationale = (
            "MiMo-via-claude cheapest on both smoke ($0.033/5-cat) "
            "and production ($0.0875/10-prompt) corpora.  Token "
            "Plan Pro $50/month buys ~6,200 audit-class dispatches.  "
            "Latency penalty (36.8s realistic vs DeepSeek 10.2s) "
            "accepted at this task class - if speed matters, use "
            "the latency task class."
        )
    elif tc == "high-volume":
        # New task class for "batch dispatch, 100s-1000s of times"
        # workloads.  MiMo TP economics dominate by a wide margin.
        primary = "mimo-via-claude"
        alternates = ("deepseek-via-claude",)
        rationale = (
            "For batch workloads (100s+ dispatches), MiMo Token Plan "
            "Pro at $50/month → 38B credits ~ 6,200 audit-class "
            "dispatches gives effectively unlimited headroom.  "
            "DeepSeek-flash at $0.055/5-category is the PAYG "
            "alternate when MiMo's tool-call markup is unacceptable."
        )
    elif tc == "multimodal":
        primary = "mimo-via-claude"
        alternates = ("kimi-via-claude",)
        rationale = (
            "After W14-MULTIMODAL-STRIP-MARKDOWN-REFS, all three "
            "engines handle stripped markdown image refs.  DeepSeek "
            "still logs a WARNING on `.png` mentions (informational) "
            "so MiMo + Kimi avoid the log noise."
        )
    elif tc == "audit":
        # For audits, we don't know the first-pass engine here; return
        # a sensible default that callers should adjust via exclude=.
        primary = "deepseek-via-claude"
        alternates = ("kimi-via-claude", "mimo-via-claude")
        rationale = (
            "Audit step needs a DIFFERENT engine than the producer.  "
            "DeepSeek v4-pro is the strongest reasoning model "
            "available; the caller should pass exclude={first-pass} "
            "to skip the original.  v4-pro is overridden via "
            "model_override (not the v4-flash default)."
        )
        # For audit task class, use deepseek-v4-pro explicitly
        return Recommendation(
            engine=_filter_excluded(primary, alternates, excluded),
            alternates=tuple(
                e for e in alternates if e not in excluded
            ),
            rationale=rationale,
            model_override=(
                "deepseek-v4-pro"
                if _pick_first(primary, alternates, excluded)
                == "deepseek-via-claude"
                else None
            ),
        )
    else:
        primary = "mimo-via-claude"
        alternates = ("kimi-via-claude", "deepseek-via-claude")
        rationale = "Default fallback."

    return Recommendation(
        engine=_filter_excluded(primary, alternates, excluded),
        alternates=tuple(e for e in alternates if e not in excluded),
        rationale=rationale,
    )


def _filter_excluded(
    primary: str,
    alternates: tuple[str, ...],
    excluded: set[str],
) -> str:
    """Return the first engine in (primary, *alternates) not in excluded.

    Raises ValueError if all candidates are excluded.
    """
    for candidate in (primary, *alternates):
        if candidate not in excluded:
            return candidate
    raise ValueError(
        f"All candidates excluded.  primary={primary}, "
        f"alternates={alternates}, excluded={sorted(excluded)}"
    )


def _pick_first(
    primary: str,
    alternates: tuple[str, ...],
    excluded: set[str],
) -> Optional[str]:
    """Best-effort pick of the first non-excluded engine, None if all excluded."""
    try:
        return _filter_excluded(primary, alternates, excluded)
    except ValueError:
        return None
