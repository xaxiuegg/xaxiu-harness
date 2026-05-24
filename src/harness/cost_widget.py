"""W11-COST-VISIBILITY-WIDGET: operator-facing 'this session cost $X' surface.

Per operator-UX panel U5 + master audit K09: operators expect cost
visibility like Claude/ChatGPT shows token counts.  Without this surface
they grep the JSONL ledger which is unfriendly.

Distinguishes tp- subscription (zero marginal cost) from sk- per-token
clearly so the operator never confuses '$0 paid' with '$0 work done'.

API:
  - cost_widget_dict(ledger_path, since_hours, budget_usd)
      Structured dict suitable for dashboard JSON / agent SDK polls.
  - format_cost_widget(ledger_path, since_hours, budget_usd)
      Single-line operator-readable text (<400 chars).

The CLI verb `harness cost-today` is wired in src/harness/cli.py.

Status thresholds:
  ok        spend < 80% of budget
  warn      80% ≤ spend < 100%
  exhausted spend ≥ 100% (remaining_usd < 0 means already over)
"""

from __future__ import annotations

import os
from pathlib import Path

import harness as _harness  # for budget_status; avoids circular

WARN_THRESHOLD = 0.80
SUBSCRIPTION_ENGINES = frozenset({
    "kimi", "kimi-api", "mimo", "mimo-pro",
    "swarm/kimi", "swarm/kimi-api", "swarm/mimo",
    "mimo-sub", "mimo-pro-sub",
})


def _window_label(since_hours: float | None) -> str:
    if since_hours is None:
        return "all-time"
    if abs(since_hours - 24.0) < 0.01:
        return "today"
    if since_hours < 1:
        return f"last {int(since_hours * 60)}min"
    if since_hours < 48:
        return f"last {since_hours:g}h"
    return f"last {since_hours / 24:g}d"


def _status_from_pct(pct: float) -> str:
    if pct >= 1.0:
        return "exhausted"
    if pct >= WARN_THRESHOLD:
        return "warn"
    return "ok"


def cost_widget_dict(ledger_path: Path | None = None,
                      since_hours: float | None = 24.0,
                      budget_usd: float | None = None) -> dict:
    """Return structured cost telemetry for dashboard + agent SDK.

    Args:
        ledger_path: Override the ledger; defaults to harness ledger.
        since_hours: Window; default 24 (today).  None = all-time.
        budget_usd: Override budget; default from COST_MAX_PER_SESSION
                    env (5.0 fallback).
    """
    bs = _harness.budget_status(since_hours=since_hours,
                                 ledger_path=ledger_path)
    spent = bs["session_cost_total"]
    if budget_usd is None:
        budget_usd = bs["cost_max_per_session_usd"]
    remaining = round(budget_usd - spent, 6)
    pct = (spent / budget_usd) if budget_usd > 0 else 0.0

    sub_disp = 0
    paid_disp = 0
    for engine, count in bs["engines_used"].items():
        if engine in SUBSCRIPTION_ENGINES:
            sub_disp += int(count)
        else:
            paid_disp += int(count)

    return {
        "spent_usd": spent,
        "budget_usd": budget_usd,
        "remaining_usd": remaining,
        "pct_of_budget_used": round(pct, 4),
        "offload_ratio": bs["offload_ratio"],
        "dispatches": bs["dispatches_fired"],
        "subscription_dispatches": sub_disp,
        "paid_dispatches": paid_disp,
        "window_label": _window_label(since_hours),
        "status": _status_from_pct(pct),
        # Keep token totals for dashboards that show them
        "tokens_total": bs["session_tokens_total"],
    }


def format_cost_widget(ledger_path: Path | None = None,
                        since_hours: float | None = 24.0,
                        budget_usd: float | None = None) -> str:
    """Return a single-line operator-readable cost summary (<400 chars).

    Example outputs:
        $0.00 spent / $5.00 budget (today) — 0 dispatches  [ok]
        $0.00 spent / $5.00 budget (today) — 2 sub, 1 paid (67% offload)  [ok]
        $4.12 spent / $5.00 budget (today) — 82% used [WARN: near budget]
        $5.40 spent / $5.00 budget (today) — over budget  [EXHAUSTED]
    """
    w = cost_widget_dict(ledger_path=ledger_path,
                          since_hours=since_hours,
                          budget_usd=budget_usd)
    if w["dispatches"] == 0:
        return (
            f"$0.00 spent / ${w['budget_usd']:.2f} budget "
            f"({w['window_label']}) — no dispatches yet  [ok]"
        )
    # Use ASCII hyphen instead of em-dash so Windows console (cp1252)
    # doesn't garble the output.
    parts = [
        f"${w['spent_usd']:.4f} spent / ${w['budget_usd']:.2f} budget",
        f"({w['window_label']})",
        f"- {w['subscription_dispatches']} sub, "
        f"{w['paid_dispatches']} paid",
        f"({int(w['offload_ratio'] * 100)}% offload)",
    ]
    line = " ".join(parts)
    if w["status"] == "exhausted":
        line += "  [EXHAUSTED — over budget]"
    elif w["status"] == "warn":
        pct = int(w["pct_of_budget_used"] * 100)
        line += f"  [WARN: {pct}% of budget — approaching cap]"
    else:
        line += "  [ok]"
    return line
