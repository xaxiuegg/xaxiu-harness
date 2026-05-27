"""W14-HARNESS-ASK 2026-05-26: daily-driver cross-engine panel CLI.

The operator types ONE command:

    harness ask "should we deprecate the legacy swarm/kimi-api backend?"

The harness fires a 3-engine panel in parallel (Kimi + MiMo + DeepSeek-flash
via Pattern B), captures each response, prints a summary table, and saves
the full responses + a synthesis-ready packet under
``coord/reviews/ask-<timestamp>/``.

This is the operator's daily driver for strategic decisions.  It packages
everything we built today: pool-aware dispatch, health-aware key
selection, automatic engine failover, routing recommender.

Design choices
==============

- Always fires all 3 Pattern B engines unless ``--engines`` overrides.
  Cross-engine diversity is the entire point of asking three; using
  only one defeats the purpose.

- Uses ``dispatch_with_pool`` so each engine's multi-key pool is
  consulted + health-aware failover applies automatically.

- Saves under ``coord/reviews/ask-YYYYMMDD-HHMMSS-<slug>/`` so the
  operator has a forever-record of every panel question + the
  3 responses it produced.

- Prints a table + opens the directory so the operator can hand the
  3 responses to in-session Claude for synthesis, or just read them.

- The harness does NOT auto-synthesize.  Synthesis benefits from
  human judgment; we surface 3 perspectives and let the operator
  decide.  An auto-synthesis option could be added later if the
  operator's workflow demands it.

CLI usage
=========

    harness ask "your question here"

    harness ask "..." --engines kimi-via-claude,deepseek-via-claude

    harness ask --file question.md             # question from a file

    harness ask "..." --output mypanel/        # custom output dir

    harness ask "..." --no-save               # don't write to disk

    harness ask "..." --max-budget-usd 0.50    # per-engine cost cap

Cost
====

Typical 3-engine audit-class panel: $0.20-0.30 total.  MiMo at TP
rates is ~$0.01 per dispatch; DeepSeek-flash ~$0.05-0.10; Kimi
~$0.05-0.10.  Total runtime ~30s-2min depending on prompt depth.
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
) -> None:
    """Write per-engine .md files + question.md + summary.json + a
    synthesis-ready packet.md under ``out_dir``."""
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

    # Summary JSON for programmatic re-use
    summary = {
        "question": question,
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
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Synthesis-ready packet: question + 3 responses concatenated.
    # The operator (or in-session Claude) can read this single file
    # to synthesize.
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
