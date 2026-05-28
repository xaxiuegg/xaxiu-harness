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
) -> AskResult:
    """Dispatch via dispatch_with_pool so multi-key + failover apply.

    ``model_override`` is forwarded to ``dispatch_with_pool(model=...)``
    — used by ``--audit`` to send v4-pro to the DeepSeek auditor when
    the recommender flags it (``recommend('audit').model_override``).
    """
    started = time.monotonic()
    try:
        from harness.engines.pool_dispatch import dispatch_with_pool
        result = dispatch_with_pool(
            engine,
            question,
            model=model_override,
            extra_args={
                "max_budget_usd": max_budget_usd,
                "timeout_s": timeout_s,
            },
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
    )


def run_panel(
    question: str,
    engines: tuple[str, ...] = DEFAULT_ENGINES,
    *,
    max_budget_usd: float = 0.30,
    timeout_s: int = 180,
) -> list[AskResult]:
    """Fire the cross-engine panel in parallel.  Returns one
    AskResult per engine in the same order as ``engines``."""
    results_by_engine: dict[str, AskResult] = {}
    with _cf.ThreadPoolExecutor(max_workers=len(engines)) as pool:
        future_to_engine = {
            pool.submit(
                _dispatch_one, eng, question, max_budget_usd, timeout_s,
            ): eng
            for eng in engines
        }
        for future in _cf.as_completed(future_to_engine):
            r = future.result()
            results_by_engine[r.engine] = r
    return [results_by_engine[eng] for eng in engines]


@dataclass
class AuditOutcome:
    """W14-ASK-AUDIT 2026-05-27: result of a producer→auditor flow.

    Either the producer failed (auditor is None, verdict is None) or
    both ran (auditor is an AskResult; verdict is the parsed dict from
    ``audit_prompt.parse_audit_verdict``).  When the auditor itself
    failed to dispatch, ``auditor`` is the failed AskResult and
    ``verdict["verdict"]`` is ``"UNKNOWN"``.
    """
    producer: AskResult
    auditor: Optional[AskResult]
    auditor_engine: str
    verdict: Optional[dict]


def run_audit(
    question: str,
    producer_engine: str,
    *,
    max_budget_usd: float = 0.30,
    timeout_s: int = 180,
    audit_engine_override: str = "",
) -> AuditOutcome:
    """Run producer → auditor sequentially.

    1. Dispatch ``producer_engine`` with the user's question.
    2. If producer failed, return (producer_result, None, None, None)
       — the audit step is skipped, since auditing a failed dispatch
       is meaningless.
    3. Otherwise pick the auditor: ``audit_engine_override`` if set,
       else ``recommend('audit', exclude={producer_engine})``.  The
       recommender returns a different engine label by construction
       (D-i: engine-label dedup, not (engine,model) dedup).
    4. Build the audit prompt via ``audit_prompt.build_audit_prompt``.
    5. Dispatch the auditor with the audit prompt + any ``model_override``
       from the recommender (e.g. ``deepseek-v4-pro``).
    6. Parse the auditor response into a structured verdict.

    Returns an ``AuditOutcome``.  Cost is producer_cost + auditor_cost
    (sequential, not parallel).
    """
    from harness.audit_prompt import build_audit_prompt, parse_audit_verdict

    producer = _dispatch_one(
        producer_engine, question, max_budget_usd, timeout_s,
    )
    if not producer.ok:
        # Audit a non-response is pointless — skip stage 2 entirely.
        return AuditOutcome(
            producer=producer, auditor=None,
            auditor_engine="", verdict=None,
        )

    # Resolve auditor + optional model override
    auditor_model_override: str = ""
    if audit_engine_override:
        auditor_engine = audit_engine_override
        # Operator override: leave model at engine default unless the
        # operator separately specifies one.  (We don't expose a
        # --audit-model flag yet; v4-pro override only applies via
        # the recommender path.)
    else:
        from harness.engines.routing_recommend import recommend
        audit_rec = recommend("audit", exclude={producer_engine})
        auditor_engine = audit_rec.engine
        auditor_model_override = audit_rec.model_override or ""

    audit_text = build_audit_prompt(
        question=question,
        producer_engine=producer_engine,
        producer_response=producer.text,
    )
    auditor = _dispatch_one(
        auditor_engine, audit_text, max_budget_usd, timeout_s,
        model_override=auditor_model_override,
    )

    if auditor.ok:
        verdict = parse_audit_verdict(auditor.text)
    else:
        verdict = {
            "verdict": "UNKNOWN",
            "summary": f"Auditor dispatch failed: {auditor.error}",
            "corrections": "",
            "missed": "",
            "overall": "",
            "raw": "",
        }

    return AuditOutcome(
        producer=producer, auditor=auditor,
        auditor_engine=auditor_engine, verdict=verdict,
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
