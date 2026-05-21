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
    "kimi":         {"input": 0.0,  "output": 0.0},
    "kimi-api":     {"input": 0.15, "output": 2.50},
    "deepseek":     {"input": 0.27, "output": 1.10},
    "deepseek-pro": {"input": 0.55, "output": 2.19},
    "anthropic":    {"input": 3.00, "output": 15.00},
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


def _compute_cost(engine: str, input_tokens: int, output_tokens: int) -> float:
    pricing = _load_pricing()
    table = pricing.get(engine)
    if table is None:
        logger.warning("Unknown engine %r; recording cost=0", engine)
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
