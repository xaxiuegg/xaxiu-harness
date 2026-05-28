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
) -> AskResult:
    """Dispatch via dispatch_with_pool so multi-key + failover apply."""
    started = time.monotonic()
    try:
        from harness.engines.pool_dispatch import dispatch_with_pool
        result = dispatch_with_pool(
            engine,
            question,
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


def save_panel(
    question: str,
    results: list[AskResult],
    out_dir: Path,
    *,
    mode: str = "panel",
    extra_summary: dict | None = None,
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
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Question file (for replay / re-runs)
    (out_dir / "question.md").write_text(
        f"# Panel question\n\n{question}\n",
        encoding="utf-8",
    )

    # Per-engine responses
    for r in results:
        safe = r.engine.replace("/", "_")
        body = [
            f"# {r.engine}",
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
            for r in results
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

    packet_lines = [
        f"# Cross-engine panel for synthesis",
        "",
        "## Question",
        "",
        question,
        "",
        "## Responses",
        "",
    ]
    for r in results:
        packet_lines.extend([
            f"### {r.engine}",
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
