"""Dispatch budget + per-engine cost ledger.

Tracks dispatch costs across engines so the operator can answer
"how much have I burned this month?" without scrolling jsonl logs.
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_LEDGER_PATH: Final = Path("coord/dev_loop/budget_ledger.jsonl")
DEFAULT_CAP_PATH: Final = Path("coord/dev_loop/budget_cap.json")

PRICING_USD_PER_M_TOKENS: Final[dict[str, dict[str, float]]] = {
    # input, output (USD per 1M tokens) — approximate published rates as of
    # v0.4.1 (2026-05-21). Vendors update frequently; verify before relying
    # on absolute totals. Operator overrides via HARNESS_BUDGET_PRICING_JSON.
    "kimi":            {"input": 0.0,   "output": 0.0},    # subscription
    "kimi-api":        {"input": 0.15,  "output": 2.50},   # Moonshot K2
    "deepseek":        {"input": 0.27,  "output": 1.10},   # DeepSeek v4-flash
    "deepseek-pro":    {"input": 0.55,  "output": 2.19},   # DeepSeek v4-pro
    "anthropic":       {"input": 3.00,  "output": 15.00},  # Claude Sonnet
    "anthropic-opus":  {"input": 15.0,  "output": 75.0},   # Claude Opus
    "gemini":          {"input": 0.075, "output": 0.30},   # Gemini 2.0 Flash
    "gemini-pro":      {"input": 1.25,  "output": 5.00},   # Gemini 2.5 Pro
}

# ---------------------------------------------------------------------------
# Env override
# ---------------------------------------------------------------------------


def _load_pricing() -> dict[str, dict[str, float]]:
    env = os.environ.get("HARNESS_BUDGET_PRICING_JSON")
    if env:
        try:
            data = json.loads(env)
            if isinstance(data, dict):
                return data  # type: ignore[return-value]
        except json.JSONDecodeError:
            warnings.warn("HARNESS_BUDGET_PRICING_JSON is invalid JSON; using defaults")
    return PRICING_USD_PER_M_TOKENS


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class CostEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    task_id: str
    engine: str
    model: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_engine(engine: str) -> str:
    """Map wrapper-style engine ids onto the canonical pricing-table key.

    The xaxiu-swarm wrapper exposes ``swarm/kimi``, ``swarm/kimi-api``,
    ``swarm/deepseek-v4-flash``, etc.  The pricing table keys these
    backends bare (``kimi``, ``kimi-api``, ``deepseek``).  This helper
    strips the ``swarm/`` prefix and folds DeepSeek variants
    (``deepseek-v4-flash``, ``deepseek-v4-pro``) onto their priced rows.

    WIRE-BUDGET-SWARM (2026-05-22): added after battle-test 2026-05-21
    surfaced "Unknown engine 'swarm/kimi'; recording cost=0" on every
    real coord-run worker dispatch.
    """
    e = engine
    if e.startswith("swarm/"):
        e = e[len("swarm/"):]
    # Fold DeepSeek model-suffix variants onto their priced bucket.
    if e in ("deepseek-v4-flash", "deepseek-v4-flash-thinking",
             "deepseek-v4-base", "deepseek-flash"):
        return "deepseek"
    if e in ("deepseek-v4-pro", "deepseek-v4-pro-thinking",
             "deepseek-pro-thinking"):
        return "deepseek-pro"
    return e


def _compute_cost(engine: str, input_tokens: int, output_tokens: int) -> float:
    pricing = _load_pricing()
    canonical = _normalize_engine(engine)
    table = pricing.get(canonical)
    if table is None:
        logger.warning("Unknown engine %r (normalized %r); recording cost=0",
                       engine, canonical)
        return 0.0
    input_cost = (input_tokens / 1_000_000) * table.get("input", 0.0)
    output_cost = (output_tokens / 1_000_000) * table.get("output", 0.0)
    return round(input_cost + output_cost, 6)


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def record_dispatch(
    *,
    task_id: str,
    engine: str,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    ledger_path: Path | None = None,
) -> CostEntry:
    """Append a CostEntry to the ledger and return it."""
    path = ledger_path or DEFAULT_LEDGER_PATH
    cost_usd = _compute_cost(engine, input_tokens, output_tokens)
    entry = CostEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        task_id=task_id,
        engine=engine,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )
    line = entry.model_dump_json() + "\n"
    data = line.encode("utf-8")
    _ensure_dir(path)
    with open(path, "ab") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return entry


def read_ledger(ledger_path: Path | None = None) -> list[CostEntry]:
    """Read all entries from the ledger (newest-last)."""
    path = ledger_path or DEFAULT_LEDGER_PATH
    if not path.exists():
        return []
    entries: list[CostEntry] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    try:
                        entries.append(CostEntry(**obj))
                    except Exception:
                        continue
    except OSError:
        return []
    return entries


def summary(
    ledger_path: Path | None = None,
    since_iso: str | None = None,
) -> dict[str, dict[str, float]]:
    """Return {engine: {dispatches, total_cost_usd, total_input_tokens, total_output_tokens}}."""
    entries = read_ledger(ledger_path)
    if since_iso:
        entries = [e for e in entries if e.timestamp >= since_iso]
    result: dict[str, dict[str, float]] = {}
    for e in entries:
        agg = result.setdefault(e.engine, {
            "dispatches": 0.0,
            "total_cost_usd": 0.0,
            "total_input_tokens": 0.0,
            "total_output_tokens": 0.0,
        })
        agg["dispatches"] += 1.0
        agg["total_cost_usd"] += e.cost_usd
        agg["total_input_tokens"] += e.input_tokens
        agg["total_output_tokens"] += e.output_tokens
    # Round for readability
    for engine in result:
        result[engine]["total_cost_usd"] = round(result[engine]["total_cost_usd"], 6)
    return result


def total_spent(
    ledger_path: Path | None = None,
    since_iso: str | None = None,
) -> float:
    """Return total USD spent."""
    entries = read_ledger(ledger_path)
    if since_iso:
        entries = [e for e in entries if e.timestamp >= since_iso]
    return round(sum(e.cost_usd for e in entries), 6)


def check_cap(
    monthly_cap_usd: float | None = None,
    ledger_path: Path | None = None,
) -> tuple[bool, float, float]:
    """Returns (within_cap, spent_this_month, cap)."""
    # Resolve cap
    if monthly_cap_usd is None:
        cap_path = DEFAULT_CAP_PATH
        if cap_path.exists():
            try:
                data = json.loads(cap_path.read_text(encoding="utf-8"))
                monthly_cap_usd = float(data.get("monthly_cap_usd", 0.0))
            except (OSError, ValueError, TypeError):
                monthly_cap_usd = 0.0
        else:
            monthly_cap_usd = 0.0

    # Filter this month
    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")
    entries = read_ledger(ledger_path)
    spent = sum(e.cost_usd for e in entries if e.timestamp.startswith(month_prefix))
    spent = round(spent, 6)

    if monthly_cap_usd <= 0.0:
        return (True, spent, monthly_cap_usd)
    return (spent < monthly_cap_usd, spent, monthly_cap_usd)


def export_daily_csv(target_dir: Path | None = None, *, date: str | None = None) -> Path:
    """Write a daily CSV roll-up of the budget ledger.

    Filters ledger entries to *date* (defaults to UTC today).  Columns:
    date, engine, model, requests, input_tokens, output_tokens, est_usd.

    Returns the CSV path written.
    """
    import csv
    from collections import defaultdict

    target_dir = target_dir or Path("coord") / "cost_daily"
    target_dir.mkdir(parents=True, exist_ok=True)
    iso_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Aggregate by (engine, model)
    agg: dict[tuple[str, str], dict[str, float | int]] = defaultdict(
        lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "est_usd": 0.0}
    )

    def _get(e: object, *keys: str) -> object:
        for k in keys:
            if isinstance(e, dict):
                if k in e:
                    return e[k]
            else:
                val = getattr(e, k, None)
                if val is not None:
                    return val
        return None

    try:
        entries = read_ledger() or []
    except Exception:
        entries = []
    for e in entries:
        ts = str(_get(e, "timestamp", "ts") or "")[:10]
        if ts != iso_date:
            continue
        engine = str(_get(e, "engine") or "unknown")
        model = str(_get(e, "model") or "-")
        bucket = agg[(engine, model)]
        bucket["requests"] += 1
        bucket["input_tokens"] += int(_get(e, "input_tokens", "tokens_in") or 0)
        bucket["output_tokens"] += int(_get(e, "output_tokens", "tokens_out", "tokens_used") or 0)
        bucket["est_usd"] += float(_get(e, "cost_usd", "usd") or 0.0)

    out_path = target_dir / f"{iso_date}.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "engine", "model", "requests",
                         "input_tokens", "output_tokens", "est_usd"])
        for (engine, model), b in sorted(agg.items()):
            writer.writerow([iso_date, engine, model,
                             b["requests"], b["input_tokens"], b["output_tokens"],
                             f"{b['est_usd']:.4f}"])
    return out_path
