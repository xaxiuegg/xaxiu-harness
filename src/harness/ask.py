"""W14-HARNESS-ASK 2026-05-26 / W14-ASK-ROUTED 2026-05-27: daily-driver
cross-engine LLM call.

THREE modes (low → high cost, low → high diversity):

  routed (default)       1 engine via routing recommender, ~$0.01-0.05
  --audit                producer → auditor (2 engines), ~$0.05
  --panel                3-engine parallel fanout, ~$0.20-0.30

The operator's daily driver is the routed default.  It uses
``harness engines recommend <task-class>`` to pick the best engine
for the task, dispatches a single call, and saves the response under
``coord/reviews/ask-YYYYMMDD-HHMMSS-<slug>/``.

The legacy 3-engine panel ("ask 3 LLMs the same question") was the
bare default before v0.5.x.  It is now opt-in via ``--panel`` and
reserved for high-stakes design crossroads where cross-vendor
diversity actually matters.

Design choices
==============

- Bare ``harness ask`` calls ``recommend("default")`` → mimo-via-claude
  (currently empirically best on the production validation corpus).
  ``--task <class>`` overrides; ``--engines X,Y,Z`` pins explicitly.

- ``--audit`` runs producer → auditor sequentially.  Producer is the
  routed default (or ``--engines`` / ``--task``); auditor is picked by
  ``recommend("audit", exclude={producer})`` so the auditor is always
  a different engine label.  Designed for catching hallucinations
  and stress-testing factual claims.

- ``--panel`` preserves the pre-v0.5.x behavior: fire all 3 Pattern B
  engines in parallel via ``run_panel``.  Output shape unchanged.

- ``--engines`` pinning ALWAYS wins.  Used by callers that need a
  specific engine (HANDOFF.md step 7, batch scripts, regression tests).

- ``dispatch_with_pool`` for every engine call, so multi-key + health-
  aware failover applies.

- Output dir convention is constant: ``coord/reviews/ask-<ts>-<slug>/``.
  Contents vary by mode; ``summary.json`` carries a ``mode`` field
  for machine readers.

CLI usage
=========

    harness ask "your question"                    # routed, 1 engine
    harness ask "..." --task latency               # routed to deepseek-flash
    harness ask "..." --audit                      # producer + auditor
    harness ask "..." --panel                      # 3-engine fanout
    harness ask "..." --engines mimo-via-claude    # explicit pin

Cost
====

  routed default      $0.01-0.05  / ~30s
  --audit             $0.05       / ~60s
  --panel             $0.20-0.30  / ~60-120s
"""
from __future__ import annotations

import concurrent.futures as _cf
import datetime
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


DEFAULT_ENGINES: tuple[str, ...] = (
    "kimi-via-claude",
    "mimo-via-claude",
    "deepseek-via-claude",
)


@dataclass
class AskResult:
    engine: str
    ok: bool
    elapsed_s: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    text: str
    error: str
    winning_alias: str
    attempt_count: int
    # W14-ASK-NOISE 2026-05-29 (reviewer gap #3): a short quality flag for a
    # response that succeeded transport-wise but is semantically garbage —
    # "empty" or "tool-noise".  "" means the answer looks real.  Surfaced in
    # the cross-vendor compare so provider machinery leakage (e.g. MiMo
    # emitting tool-call markup) doesn't silently corrupt the comparison.
    noise: str = ""


# Literal machinery tokens that indicate a provider leaked its tool-call /
# function-call scaffolding into the answer text instead of returning prose.
# Deliberately SPECIFIC (full tags / sentinel tokens), never bare words like
# "function", so a legitimate prose answer about functions is not flagged.
_TOOL_NOISE_MARKERS: tuple[str, ...] = (
    "<tool_call>", "</tool_call>", "<tool_calls>", '"tool_calls":',
    "<|tool_calls_section_begin|>", "<|tool_call_begin|>",
    "<｜tool▁calls▁begin｜>", "<｜tool▁call▁begin｜>",
    "<function_calls>", "<invoke name=",
    "$web_search", '"builtin_function"',
)


def _assess_noise(text: str) -> str:
    """Classify a *successful* engine response for obvious garbage.

    Returns ``"empty"`` (blank/whitespace body), ``"tool-noise"`` (provider
    tool-call scaffolding leaked into the text), or ``""`` when the response
    looks like a real answer.  Conservative by design — only unambiguous
    machinery tokens count, so a genuine prose answer is never flagged.
    """
    stripped = (text or "").strip()
    if not stripped:
        return "empty"
    if any(marker in stripped for marker in _TOOL_NOISE_MARKERS):
        return "tool-noise"
    return ""


def _slugify(question: str, max_len: int = 40) -> str:
    """Return a filesystem-safe slug for the output dir name."""
    text = question.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:max_len] or "unnamed"


def _dispatch_one(
    engine: str,
    question: str,
    max_budget_usd: float,
    timeout_s: int,
    *,
    model_override: str = "",
    effort: str = "",
    agentic: bool = False,
) -> AskResult:
    """Dispatch via dispatch_with_pool so multi-key + failover apply.

    ``model_override`` is forwarded to ``dispatch_with_pool(model=...)``
    — used by ``--audit`` to send v4-pro to the DeepSeek auditor when
    the recommender flags it (``recommend('audit').model_override``).

    ``agentic`` drops ``--bare`` + offers a tool allowlist (WebFetch /
    WebSearch / Task / file + Bash).  Honoured only by the subscription
    ``claude-via-cc`` engine (gated in its ``_build_command``); other
    engines ignore the extra key.
    """
    started = time.monotonic()
    extra: dict = {"max_budget_usd": max_budget_usd, "timeout_s": timeout_s}
    if effort:
        extra["effort"] = effort
    if agentic:
        extra["agentic"] = True

    # Direct-dispatch engine (no poolable HTTP key): kimi-cli is a local-CLI
    # subprocess agent (subagents + web research via the Kimi CLI).  It
    # bypasses the multi-key pool and dispatches directly.
    if engine == "kimi-cli":
        try:
            from harness.engines.concrete import get_engine
            resp = get_engine(engine).dispatch(
                question, model_override or "", extra,
            )
        except Exception as exc:
            return AskResult(
                engine=engine, ok=False,
                elapsed_s=time.monotonic() - started,
                tokens_in=0, tokens_out=0, cost_usd=0.0,
                text="", error=f"{type(exc).__name__}: {exc}",
                winning_alias="", attempt_count=1,
            )
        return AskResult(
            engine=engine, ok=bool(resp.success),
            elapsed_s=time.monotonic() - started,
            tokens_in=int(resp.tokens_in or 0),
            tokens_out=int(resp.tokens_out or 0),
            cost_usd=float(getattr(resp, "cost_usd", 0.0) or 0.0),
            text=resp.text if resp.success else "",
            error=resp.error if not resp.success else "",
            winning_alias="kimi-cli",
            attempt_count=1,
            noise=_assess_noise(resp.text) if resp.success else "",
        )

    try:
        from harness.engines.pool_dispatch import dispatch_with_pool
        result = dispatch_with_pool(
            engine,
            question,
            model=model_override,
            extra_args=extra,
            max_retries=3,
        )
    except Exception as exc:
        return AskResult(
            engine=engine, ok=False,
            elapsed_s=time.monotonic() - started,
            tokens_in=0, tokens_out=0, cost_usd=0.0,
            text="", error=f"{type(exc).__name__}: {exc}",
            winning_alias="", attempt_count=0,
        )
    elapsed = time.monotonic() - started
    resp = result.response
    return AskResult(
        engine=engine,
        ok=bool(result.success),
        elapsed_s=elapsed,
        tokens_in=int(resp.tokens_in or 0) if resp else 0,
        tokens_out=int(resp.tokens_out or 0) if resp else 0,
        cost_usd=float(resp.cost_usd or 0.0) if resp else 0.0,
        text=resp.text if resp and result.success else "",
        error=resp.error if resp and not result.success else "",
        winning_alias=result.winning_alias,
        attempt_count=result.attempt_count,
        noise=_assess_noise(resp.text) if (resp and result.success) else "",
    )


def run_panel(
    question: str,
    engines: tuple[str, ...] = DEFAULT_ENGINES,
    *,
    max_budget_usd: float = 0.30,
    timeout_s: int = 180,
    effort: str = "",
    agentic: bool = False,
) -> list[AskResult]:
    """Fire the cross-engine panel in parallel.  Returns one
    AskResult per engine in the same order as ``engines``."""
    results_by_engine: dict[str, AskResult] = {}
    with _cf.ThreadPoolExecutor(max_workers=len(engines)) as pool:
        future_to_engine = {
            pool.submit(
                _dispatch_one, eng, question, max_budget_usd, timeout_s,
                effort=effort, agentic=agentic,
            ): eng
            for eng in engines
        }
        for future in _cf.as_completed(future_to_engine):
            r = future.result()
            results_by_engine[r.engine] = r
    return [results_by_engine[eng] for eng in engines]


from dataclasses import field as _field


@dataclass
class AuditOutcome:
    """W14-ASK-AUDIT 2026-05-27 / W14-AUDITORS-QUORUM 2026-05-28: result
    of a producer→auditor(s) flow.

    For single-auditor (default): ``auditors`` has 1 entry, ``verdict``
    is the parsed verdict dict.

    For multi-auditor (quorum): ``auditors`` has N entries (parallel
    dispatch); ``verdicts`` has per-auditor parsed dicts; ``verdict``
    is the AGGREGATE — a dict with ``verdict`` ∈ {PASS, PARTIAL, FAIL,
    UNKNOWN} computed from the per-auditor scores (PASS=2, PARTIAL=1,
    FAIL=0, UNKNOWN=null), plus an ``auditor_breakdown`` field listing
    each auditor's per-engine verdict.

    Backward compat: the legacy single-auditor ``auditor`` /
    ``auditor_engine`` fields point at the FIRST auditor.

    Producer failure: ``auditors`` is empty, ``verdict`` is None.
    """
    producer: AskResult
    auditor: Optional[AskResult]
    auditor_engine: str
    verdict: Optional[dict]
    # Multi-auditor extension (W14-AUDITORS-QUORUM 2026-05-28).
    # For N=1 these are also populated (1-entry lists); callers that
    # only care about single-auditor can keep using `auditor` /
    # `auditor_engine` / `verdict`.
    auditors: list[AskResult] = _field(default_factory=list)
    auditor_engines: list[str] = _field(default_factory=list)
    verdicts: list[Optional[dict]] = _field(default_factory=list)


def _aggregate_verdicts(verdicts: list[Optional[dict]]) -> dict:
    """Compute a quorum-aggregate verdict across N auditor verdicts.

    Scoring:  PASS=2, PARTIAL=1, FAIL=0, UNKNOWN=excluded-from-average.

    Aggregate:
      - All UNKNOWN → UNKNOWN
      - avg >= 1.5 → PASS
      - 0.5 < avg < 1.5 → PARTIAL
      - avg <= 0.5 → FAIL

    Returns a dict shaped like a single-auditor verdict:
      {verdict, summary, corrections, missed, overall, raw,
       auditor_breakdown}.

    ``auditor_breakdown`` is a list of per-auditor mini-dicts so the
    caller can see WHY the aggregate landed where it did.
    """
    score_map = {"PASS": 2, "PARTIAL": 1, "FAIL": 0}
    scores = []
    breakdown = []
    summaries = []
    corrections = []
    missed = []
    overalls = []
    for i, v in enumerate(verdicts):
        if v is None:
            breakdown.append({"index": i, "verdict": "MISSING"})
            continue
        vv = (v.get("verdict") or "UNKNOWN").upper()
        breakdown.append({"index": i, "verdict": vv})
        if vv in score_map:
            scores.append(score_map[vv])
        if v.get("summary"):
            summaries.append(f"({vv}) {v['summary']}")
        if v.get("corrections") and v["corrections"].lower() != "none":
            corrections.append(f"[auditor {i}] {v['corrections']}")
        if v.get("missed") and v["missed"].lower() != "none":
            missed.append(f"[auditor {i}] {v['missed']}")
        if v.get("overall"):
            overalls.append(f"[auditor {i}] {v['overall']}")

    if not scores:
        agg = "UNKNOWN"
    else:
        avg = sum(scores) / len(scores)
        if avg >= 1.5:
            agg = "PASS"
        elif avg > 0.5:
            agg = "PARTIAL"
        else:
            agg = "FAIL"

    quorum_summary = f"Quorum of {len(verdicts)} auditors → {agg}"
    if scores and len(set(scores)) > 1:
        # Mixed verdicts: explicitly label
        per = " / ".join(b["verdict"] for b in breakdown)
        quorum_summary += f" (split: {per})"

    return {
        "verdict": agg,
        "summary": quorum_summary,
        "corrections": "\n".join(corrections) if corrections else "none",
        "missed": "\n".join(missed) if missed else "none",
        "overall": "\n\n".join(overalls),
        "raw": "",  # aggregate has no raw text; per-auditor raws kept on verdicts
        "auditor_breakdown": breakdown,
    }


def _pick_auditor_engines(
    producer_engine: str,
    num_auditors: int,
) -> list[tuple[str, str]]:
    """Walk the health-aware recommender to pick up to N distinct
    auditor engines.

    Returns list of (engine_name, model_override) tuples in priority
    order.  Capped at the number of unique HEALTHY alternates available
    — if only 2 distinct engines remain after excluding producer + dead
    engines, returning 2 even when N=3 is requested.

    W14-DISPATCH-HEALTH-AWARE-FALLBACK 2026-05-28: now uses
    ``recommend_healthy()`` to skip recently-terminated engines.
    """
    from harness.engines.routing_recommend import recommend_healthy
    excludes = {producer_engine}
    out: list[tuple[str, str]] = []
    for _ in range(num_auditors):
        rec = recommend_healthy("audit", exclude=excludes)
        if rec is None or rec.engine in excludes:
            break
        out.append((rec.engine, rec.model_override or ""))
        excludes.add(rec.engine)
    return out


def run_audit(
    question: str,
    producer_engine: str,
    *,
    max_budget_usd: float = 0.30,
    timeout_s: int = 180,
    audit_engine_override: str = "",
    num_auditors: int = 1,
    effort: str = "",
    agentic: bool = False,
) -> AuditOutcome:
    """Run producer → auditor(s).

    1. Dispatch ``producer_engine`` with the user's question.
    2. If producer failed, return outcome with empty auditors list.
    3. Pick auditor engine(s):
       - If ``audit_engine_override`` set: single override engine.
       - Else if ``num_auditors == 1``: ``recommend('audit',
         exclude={producer})``.  Same as pre-v0.6.x behavior.
       - Else: walk ``recommend`` N times, picking distinct alternates.
         If fewer than N alternates exist, cap at what's available.
    4. Build the audit prompt once (same producer answer for all
       auditors).
    5. Dispatch auditor(s) in PARALLEL via ThreadPoolExecutor.
    6. Parse each auditor response.  For N>1, aggregate via majority
       (PASS=2, PARTIAL=1, FAIL=0).

    Returns an ``AuditOutcome``.  Cost ≈ producer + N×auditor.
    """
    from harness.audit_prompt import build_audit_prompt, parse_audit_verdict

    # ``agentic`` applies only to the producer (auditors are cross-vendor
    # providers returning verdict text; agentic is subscription-gated and
    # inert for them anyway).
    producer = _dispatch_one(
        producer_engine, question, max_budget_usd, timeout_s,
        effort=effort, agentic=agentic,
    )
    if not producer.ok:
        return AuditOutcome(
            producer=producer, auditor=None,
            auditor_engine="", verdict=None,
            auditors=[], auditor_engines=[], verdicts=[],
        )

    # Resolve auditor engine(s).  Override takes precedence and
    # forces num_auditors=1 (overriding 1 engine + then needing N-1
    # alternates is an inconsistent request).
    if audit_engine_override:
        auditor_specs: list[tuple[str, str]] = [
            (audit_engine_override, ""),
        ]
    else:
        auditor_specs = _pick_auditor_engines(
            producer_engine, num_auditors,
        )

    if not auditor_specs:
        return AuditOutcome(
            producer=producer, auditor=None,
            auditor_engine="", verdict=None,
            auditors=[], auditor_engines=[], verdicts=[],
        )

    # Build audit prompt once + dispatch each auditor in parallel
    audit_text = build_audit_prompt(
        question=question,
        producer_engine=producer_engine,
        producer_response=producer.text,
    )

    if len(auditor_specs) == 1:
        # Single-auditor path — sequential, no thread-pool overhead
        eng, model = auditor_specs[0]
        auditor = _dispatch_one(
            eng, audit_text, max_budget_usd, timeout_s,
            model_override=model,
        )
        auditors = [auditor]
    else:
        # Multi-auditor: fan out in parallel.  max_workers = N keeps
        # the pool exactly sized to the work.
        auditors_by_engine: dict[str, AskResult] = {}
        with _cf.ThreadPoolExecutor(
            max_workers=len(auditor_specs),
        ) as pool:
            future_to_eng = {
                pool.submit(
                    _dispatch_one, eng, audit_text,
                    max_budget_usd, timeout_s,
                    model_override=model,
                ): eng
                for eng, model in auditor_specs
            }
            for future in _cf.as_completed(future_to_eng):
                r = future.result()
                auditors_by_engine[r.engine] = r
        # Preserve auditor_specs ordering in the returned list
        auditors = [
            auditors_by_engine[eng] for eng, _ in auditor_specs
            if eng in auditors_by_engine
        ]

    # Parse each auditor's verdict
    verdicts: list[Optional[dict]] = []
    for a in auditors:
        if a.ok:
            verdicts.append(parse_audit_verdict(a.text))
        else:
            verdicts.append({
                "verdict": "UNKNOWN",
                "summary": f"Auditor dispatch failed: {a.error}",
                "corrections": "",
                "missed": "",
                "overall": "",
                "raw": "",
            })

    # Aggregate (trivial for N=1: aggregate IS the single verdict)
    if len(verdicts) == 1:
        verdict = verdicts[0]
    else:
        verdict = _aggregate_verdicts(verdicts)

    return AuditOutcome(
        producer=producer,
        auditor=auditors[0],                       # back-compat alias
        auditor_engine=auditors[0].engine,         # back-compat alias
        verdict=verdict,                           # aggregate for N>1
        auditors=auditors,
        auditor_engines=[a.engine for a in auditors],
        verdicts=verdicts,
    )


def save_panel(
    question: str,
    results: list[AskResult],
    out_dir: Path,
    *,
    mode: str = "panel",
    extra_summary: dict | None = None,
    roles: list[str] | None = None,
) -> None:
    """Write per-engine .md files + question.md + summary.json (+ packet.md
    for multi-engine modes) under ``out_dir``.

    Parameters
    ----------
    question
        The user's question (rendered into ``question.md``).
    results
        Per-engine AskResult list.  One file is written per result.
    out_dir
        Output directory.  Created if missing.
    mode
        Output mode.  ``"routed"`` (single engine, no packet),
        ``"panel"`` (current 3-engine behavior, with packet),
        ``"audit"`` (producer + auditor, with packet), or any other
        string (treated as panel-style for forward-compat).  Stored
        in ``summary.json`` so machine readers can tell.
    extra_summary
        Additional keys to merge into ``summary.json``.  Used by
        ``--audit`` to surface the parsed verdict.
    roles
        Optional list of role tags, parallel to ``results``.  Each
        non-empty role becomes a filename prefix (e.g. role
        ``"producer"`` + engine ``"mimo-via-claude"`` writes
        ``producer-mimo-via-claude.md``).  Used by ``--audit`` to
        distinguish producer + auditor in the output dir.  If None
        or shorter than results, missing entries default to no prefix.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Question file (for replay / re-runs)
    (out_dir / "question.md").write_text(
        f"# Panel question\n\n{question}\n",
        encoding="utf-8",
    )

    # Per-engine responses
    def _role_for(i: int) -> str:
        return roles[i] if (roles and i < len(roles)) else ""

    for i, r in enumerate(results):
        safe = r.engine.replace("/", "_")
        role = _role_for(i)
        if role:
            safe = f"{role}-{safe}"
            heading = f"# {role}: {r.engine}"
        else:
            heading = f"# {r.engine}"
        body = [
            heading,
            "",
            f"**latency**: {r.elapsed_s:.1f}s   "
            f"**tokens_in**: {r.tokens_in}   "
            f"**tokens_out**: {r.tokens_out}   "
            f"**cost**: ${r.cost_usd:.4f}",
            f"**winning_alias**: {r.winning_alias or '—'}   "
            f"**attempts**: {r.attempt_count}",
            "",
            "---",
            "",
        ]
        if r.ok:
            body.append(r.text)
        else:
            body.append(f"DISPATCH FAILED: {r.error}")
        (out_dir / f"{safe}.md").write_text(
            "\n".join(body), encoding="utf-8",
        )

    # Summary JSON for programmatic re-use.  ``mode`` is the load-
    # bearing field for downstream tools (forensic scans, dashboards).
    summary = {
        "question": question,
        "mode": mode,
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc,
        ).isoformat(),
        "results": [
            {
                "engine": r.engine,
                "role": _role_for(i),
                "ok": r.ok,
                "elapsed_s": r.elapsed_s,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "cost_usd": r.cost_usd,
                "winning_alias": r.winning_alias,
                "attempt_count": r.attempt_count,
                "text_excerpt": r.text[:300].replace("\n", " "),
                "error": r.error,
            }
            for i, r in enumerate(results)
        ],
        "total_cost_usd": sum(r.cost_usd for r in results),
        "max_latency_s": max(
            (r.elapsed_s for r in results), default=0.0,
        ),
    }
    if extra_summary:
        summary.update(extra_summary)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Synthesis-ready packet.  Routed (single-engine) mode skips this
    # because there is nothing to concatenate — the lone per-engine
    # file IS the synthesis-ready artifact.  Panel + audit modes write
    # packet.md so callers can hand a single file to a synthesizing
    # agent.
    if mode == "routed":
        return

    title = (
        "# Producer → Auditor (--audit synthesis)"
        if mode == "audit"
        else "# Cross-engine panel for synthesis"
    )
    packet_lines = [
        title,
        "",
        "## Question",
        "",
        question,
        "",
        "## Responses",
        "",
    ]
    for i, r in enumerate(results):
        role = _role_for(i)
        section_label = f"{role}: {r.engine}" if role else r.engine
        packet_lines.extend([
            f"### {section_label}",
            "",
            f"_latency {r.elapsed_s:.1f}s, "
            f"cost ${r.cost_usd:.4f}, "
            f"alias {r.winning_alias or '—'}_",
            "",
        ])
        if r.ok:
            packet_lines.append(r.text)
        else:
            packet_lines.append(f"**FAILED**: {r.error}")
        packet_lines.append("")
    (out_dir / "packet.md").write_text(
        "\n".join(packet_lines), encoding="utf-8",
    )
