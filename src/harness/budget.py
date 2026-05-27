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
    # Xiaomi MiMo Open Platform — Overseas API rates, ≤256K context slice
    # (platform.xiaomimimo.com/docs/en-US/pricing, verified 2026-05-22).
    # These are cache-miss rates for input; cache hits are ~5x cheaper
    # (Pro: $0.20 hit / $1.00 miss; Standard: $0.08 hit / $0.40 miss).
    # The harness records cache-miss conservatively; refine when we
    # plumb cache-hit telemetry.
    #
    # Token Plan subscription (``tp-`` key prefix) maps to the ``-sub``
    # rows so credit-based dispatches cost $0 in the per-token ledger.
    # Actual credit burn (Pro=2x, Standard=1x) is tracked separately if
    # the operator wires a credits sub-ledger.
    "mimo":            {"input": 0.40,  "output": 2.00},   # MiMo V2.5 std (≤256K cache-miss)
    "mimo-pro":        {"input": 1.00,  "output": 3.00},   # MiMo V2.5-Pro (≤256K cache-miss)
    "mimo-long":       {"input": 0.80,  "output": 4.00},   # MiMo V2.5 std (256K–1M slice)
    "mimo-pro-long":   {"input": 2.00,  "output": 6.00},   # MiMo V2.5-Pro (256K–1M slice)
    "mimo-sub":        {"input": 0.0,   "output": 0.0},    # tp- key → free
    "mimo-pro-sub":    {"input": 0.0,   "output": 0.0},    # tp- key → free
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
    # P3 audit fix (2026-05-27): True iff cost_usd was computed from a
    # populated pricing-table row.  False iff the engine name was unknown
    # to the pricing table AND not a documented free engine (mock/etc).
    # Old ledger rows lack this field and deserialize with the default
    # True — strictly that's optimistic, but presence-known rows are
    # rare in practice and the default avoids retroactively flagging
    # the whole historical ledger as "incomplete".
    cost_known: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_engine(engine: str) -> str:
    """Map wrapper-style engine ids onto the canonical pricing-table key.

    The xaxiu-swarm wrapper exposes ``swarm/kimi``, ``swarm/kimi-api``,
    ``swarm/deepseek-v4-flash``, etc.  The pricing table keys these
    backends bare (``kimi``, ``kimi-api``, ``deepseek``).  This helper
    strips the ``swarm/`` prefix and folds DeepSeek + MiMo variants
    onto their priced rows.

    WIRE-BUDGET-SWARM (2026-05-22): added after battle-test 2026-05-21
    surfaced "Unknown engine 'swarm/kimi'; recording cost=0" on every
    real coord-run worker dispatch.

    WIRE-MIMO-BUDGET (2026-05-22): when the operator's MIMO_API_KEY
    starts with ``tp-`` (Token Plan subscription), MiMo dispatches map
    to the zero-cost ``-sub`` pricing rows so the ledger reflects
    actual spend.  ``sk-`` keys retain the published per-token rates.
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
    # MiMo variants
    if e in ("mimo-v2.5", "mimo-v25", "mimo-standard", "mimo"):
        return _mimo_pricing_row(base="mimo")
    if e in ("mimo-v2.5-pro", "mimo-v25-pro", "mimo-pro"):
        return _mimo_pricing_row(base="mimo-pro")
    return e


def _mimo_pricing_row(*, base: str) -> str:
    """Return base or base+``-sub`` based on MIMO_API_KEY prefix."""
    key = os.environ.get("MIMO_API_KEY", "")
    if key.startswith("tp-"):
        return f"{base}-sub"
    return base


_KNOWN_FREE_ENGINES = frozenset({"mock", "mock-engine", "mockengine"})


def _compute_cost(
    engine: str, input_tokens: int, output_tokens: int,
) -> tuple[float, bool]:
    """Compute the dispatch cost AND report whether the engine was priced.

    Returns ``(cost_usd, cost_known)`` where ``cost_known`` is False iff
    the engine name was unknown to the pricing table AND not a documented
    free engine.  Callers persist ``cost_known`` to the ledger so the
    operator-facing budget surfaces can flag the meter as undercounting
    instead of silently returning $0.00.

    P3 audit fix (2026-05-27): a ``logger.warning`` was previously the
    only signal here — and a non-technical operator never sees log
    output, so a renamed/unknown engine showed up as silent $0 forever.
    """
    pricing = _load_pricing()
    canonical = _normalize_engine(engine)
    table = pricing.get(canonical)
    if table is None:
        # W5-G 2026-05-22: 'mock' is a documented free pseudo-engine used
        # by the v2 coord smoke test; warning on every dispatch was pure
        # noise.  Stay silent for the documented free engines.
        if canonical in _KNOWN_FREE_ENGINES:
            return 0.0, True  # known free engine — $0 is accurate
        logger.warning(
            "Unknown engine %r (normalized %r); recording cost=0 with "
            "cost_known=False (operator: this dispatch will show as "
            "UNPRICED in `harness budget summary`)",
            engine, canonical,
        )
        return 0.0, False
    input_cost = (input_tokens / 1_000_000) * table.get("input", 0.0)
    output_cost = (output_tokens / 1_000_000) * table.get("output", 0.0)
    return round(input_cost + output_cost, 6), True


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
    """Append a CostEntry to the ledger and return it.

    P3 audit fix (2026-05-27): ``cost_known`` is persisted on the entry
    so downstream budget surfaces can flag unpriced dispatches instead
    of silently aggregating them as $0.00.
    """
    path = ledger_path or DEFAULT_LEDGER_PATH
    cost_usd, cost_known = _compute_cost(engine, input_tokens, output_tokens)
    entry = CostEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        task_id=task_id,
        engine=engine,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        cost_known=cost_known,
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
    """Return {engine: {dispatches, total_cost_usd, total_input_tokens,
    total_output_tokens, unpriced_dispatches}}.

    P3 audit fix (2026-05-27): added ``unpriced_dispatches`` per engine
    counting rows where ``cost_known=False``.  Operators surfacing this
    aggregate can show ``"unpriced dispatches: N (cost unknown)"``
    instead of silently aggregating them as $0.
    """
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
            "unpriced_dispatches": 0.0,  # P3 audit fix
        })
        agg["dispatches"] += 1.0
        agg["total_cost_usd"] += e.cost_usd
        agg["total_input_tokens"] += e.input_tokens
        agg["total_output_tokens"] += e.output_tokens
        if not e.cost_known:
            agg["unpriced_dispatches"] += 1.0
    # Round for readability
    for engine in result:
        result[engine]["total_cost_usd"] = round(result[engine]["total_cost_usd"], 6)
    return result


def unpriced_engines_since(
    ledger_path: Path | None = None,
    since_iso: str | None = None,
) -> dict[str, int]:
    """Return ``{engine_name: unpriced_dispatch_count}`` across the window.

    Convenience helper for UIs surfacing unpriced-engine warnings.  Only
    includes engines with at least one unpriced row.

    P3 audit fix (2026-05-27).
    """
    entries = read_ledger(ledger_path)
    if since_iso:
        entries = [e for e in entries if e.timestamp >= since_iso]
    out: dict[str, int] = {}
    for e in entries:
        if not e.cost_known:
            out[e.engine] = out.get(e.engine, 0) + 1
    return out


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


# ---------------------------------------------------------------------------
# W14-BUDGET-METER-PER-ENGINE 2026-05-25
#
# Per-engine monthly caps on top of the existing global monthly_cap_usd.
# Schema (backward-compat: old files without per_engine_caps_usd still work):
#
#   {
#     "monthly_cap_usd": 195.0,
#     "per_engine_caps_usd": {
#       "deepseek": 30.0,
#       "mimo": 15.0,
#       "qwen": 50.0
#     },
#     "alert_threshold_pct": 80
#   }
#
# Operator commit (2026-05-25): $100 Claude Code direct + $15 MiMo TP +
# $30 DeepSeek PAYG + $50 Qwen 3.6 Plus PAYG = $195/mo, with the harness
# enforcing the per-engine slice ($15/$30/$50 visible here; Claude
# subscription is direct + not harness-mediated).
# ---------------------------------------------------------------------------

# Default alert threshold (pct).  80% means an observer flag fires at 80%
# of cap, giving the operator headroom to reroute before hitting refusal.
DEFAULT_ALERT_THRESHOLD_PCT: Final = 80


class EngineCapStatus(BaseModel):
    """Per-engine cap status for one engine over the current month."""
    model_config = ConfigDict(extra="forbid")

    engine: str
    spent_usd: float = Field(ge=0.0)
    cap_usd: float = Field(ge=0.0)
    pct_used: float = Field(ge=0.0)  # spent / cap * 100, 0 if cap=0
    within_cap: bool
    alert_threshold_reached: bool
    # When alert_threshold_pct is e.g. 80, alert_threshold_reached=True
    # if spent >= 80% of cap.


def read_caps_config(
    cap_path: Path | None = None,
) -> dict:
    """Read the (possibly-extended) cap config.

    Returns a dict with three keys:
      - monthly_cap_usd: float (global cap, 0.0 if absent)
      - per_engine_caps_usd: dict[str, float] (empty dict if absent)
      - alert_threshold_pct: int (80 if absent)

    Backward-compatible with the v1 single-cap schema (just
    {"monthly_cap_usd": N}) — extra keys default to empty/default.
    """
    path = cap_path or DEFAULT_CAP_PATH
    if not path.exists():
        return {
            "monthly_cap_usd": 0.0,
            "per_engine_caps_usd": {},
            "alert_threshold_pct": DEFAULT_ALERT_THRESHOLD_PCT,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {
            "monthly_cap_usd": 0.0,
            "per_engine_caps_usd": {},
            "alert_threshold_pct": DEFAULT_ALERT_THRESHOLD_PCT,
        }
    if not isinstance(data, dict):
        return {
            "monthly_cap_usd": 0.0,
            "per_engine_caps_usd": {},
            "alert_threshold_pct": DEFAULT_ALERT_THRESHOLD_PCT,
        }
    try:
        global_cap = float(data.get("monthly_cap_usd", 0.0))
    except (ValueError, TypeError):
        global_cap = 0.0
    raw_per_engine = data.get("per_engine_caps_usd", {})
    per_engine: dict[str, float] = {}
    if isinstance(raw_per_engine, dict):
        for k, v in raw_per_engine.items():
            try:
                per_engine[str(k)] = float(v)
            except (ValueError, TypeError):
                continue
    try:
        alert_pct = int(data.get("alert_threshold_pct",
                                  DEFAULT_ALERT_THRESHOLD_PCT))
    except (ValueError, TypeError):
        alert_pct = DEFAULT_ALERT_THRESHOLD_PCT
    if alert_pct < 0:
        alert_pct = 0
    if alert_pct > 100:
        alert_pct = 100
    return {
        "monthly_cap_usd": global_cap,
        "per_engine_caps_usd": per_engine,
        "alert_threshold_pct": alert_pct,
    }


def write_caps_config(
    config: dict,
    cap_path: Path | None = None,
) -> None:
    """Persist the cap config dict to JSON.  Schema validation is best-effort —
    we serialize whatever's in the dict using the same keys that
    ``read_caps_config`` recognizes.
    """
    path = cap_path or DEFAULT_CAP_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = {
        "monthly_cap_usd": float(config.get("monthly_cap_usd", 0.0)),
        "per_engine_caps_usd": {
            str(k): float(v)
            for k, v in (config.get("per_engine_caps_usd") or {}).items()
        },
        "alert_threshold_pct": int(config.get(
            "alert_threshold_pct", DEFAULT_ALERT_THRESHOLD_PCT,
        )),
    }
    path.write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")


def set_engine_cap(
    engine: str,
    amount_usd: float,
    cap_path: Path | None = None,
) -> None:
    """Update one engine's cap.  Preserves all other caps + global cap."""
    config = read_caps_config(cap_path)
    if amount_usd <= 0.0:
        # Allow removing a cap by setting it to 0
        config["per_engine_caps_usd"].pop(engine, None)
    else:
        config["per_engine_caps_usd"][engine] = float(amount_usd)
    write_caps_config(config, cap_path)


def _spent_this_month_by_engine(
    ledger_path: Path | None = None,
) -> dict[str, float]:
    """Sum USD spent per engine across this calendar month (UTC)."""
    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")
    entries = read_ledger(ledger_path)
    out: dict[str, float] = {}
    for e in entries:
        if not e.timestamp.startswith(month_prefix):
            continue
        # Normalize to the same canonical key the pricing table uses,
        # so caps for "deepseek" apply whether the dispatch logged
        # "swarm/deepseek-v4-flash" or "deepseek".
        canonical = _normalize_engine(e.engine)
        # Strip MiMo subscription tag — the operator caps the engine,
        # not the pricing variant.  "mimo-sub" and "mimo" share a cap.
        if canonical.endswith("-sub"):
            canonical = canonical[: -len("-sub")]
        if canonical.endswith("-pro"):
            # Operator caps go on the engine family, not pro vs std
            canonical = canonical[: -len("-pro")]
        if canonical.endswith("-long"):
            canonical = canonical[: -len("-long")]
        out[canonical] = round(out.get(canonical, 0.0) + e.cost_usd, 6)
    return out


def check_engine_cap(
    engine: str,
    *,
    ledger_path: Path | None = None,
    caps_config: dict | None = None,
) -> EngineCapStatus:
    """Return the cap status for one engine over the current month.

    ``engine`` is the canonical engine key (e.g. "deepseek", "mimo",
    "qwen", "kimi", "anthropic", "gemini").  Variants like
    "deepseek-v4-flash", "mimo-v2.5-pro", "swarm/kimi" are folded onto
    their canonical key via ``_normalize_engine``.
    """
    config = caps_config if caps_config is not None else read_caps_config()
    per_engine = config.get("per_engine_caps_usd", {})
    alert_pct_threshold = int(config.get(
        "alert_threshold_pct", DEFAULT_ALERT_THRESHOLD_PCT,
    ))

    canonical = _normalize_engine(engine)
    if canonical.endswith("-sub"):
        canonical = canonical[: -len("-sub")]
    if canonical.endswith("-pro"):
        canonical = canonical[: -len("-pro")]
    if canonical.endswith("-long"):
        canonical = canonical[: -len("-long")]
    cap_usd = float(per_engine.get(canonical, 0.0))

    by_engine = _spent_this_month_by_engine(ledger_path)
    spent = float(by_engine.get(canonical, 0.0))

    if cap_usd <= 0.0:
        # No cap configured for this engine — always within, no alert
        return EngineCapStatus(
            engine=canonical,
            spent_usd=round(spent, 6),
            cap_usd=0.0,
            pct_used=0.0,
            within_cap=True,
            alert_threshold_reached=False,
        )

    pct_used = (spent / cap_usd) * 100.0 if cap_usd > 0 else 0.0
    return EngineCapStatus(
        engine=canonical,
        spent_usd=round(spent, 6),
        cap_usd=round(cap_usd, 6),
        pct_used=round(pct_used, 2),
        within_cap=spent < cap_usd,
        alert_threshold_reached=pct_used >= alert_pct_threshold,
    )


def all_engines_status(
    *,
    ledger_path: Path | None = None,
    caps_config: dict | None = None,
) -> list[EngineCapStatus]:
    """Return cap status for every engine that has either a cap configured
    or any spend recorded this month.  Sorted by engine name.
    """
    config = caps_config if caps_config is not None else read_caps_config()
    per_engine = config.get("per_engine_caps_usd", {})
    by_engine = _spent_this_month_by_engine(ledger_path)
    engines = sorted(set(per_engine.keys()) | set(by_engine.keys()))
    return [
        check_engine_cap(
            eng, ledger_path=ledger_path, caps_config=config,
        )
        for eng in engines
    ]


class CapExceededError(RuntimeError):
    """Raised when ``enforce_engine_cap`` is called for an over-cap engine.

    The error message names the engine, current spend, and cap so the
    operator immediately sees the gap.  Categorized as the
    ``quota-exceeded`` bucket in ``cli_helpers.categorize_engine_failure``
    when surfaced to dispatch callers.
    """

    def __init__(self, status: EngineCapStatus) -> None:
        self.status = status
        super().__init__(
            f"engine cap exceeded for {status.engine!r}: "
            f"spent ${status.spent_usd:.4f} of ${status.cap_usd:.2f} "
            f"({status.pct_used:.1f}% used)"
        )


def enforce_engine_cap(
    engine: str,
    *,
    ledger_path: Path | None = None,
    caps_config: dict | None = None,
) -> EngineCapStatus:
    """Check the cap and raise ``CapExceededError`` if over.

    Returns the ``EngineCapStatus`` on success (within-cap path), so
    callers can inspect ``alert_threshold_reached`` to emit warnings
    without a separate query.

    Opt-in by design — only raises when a cap is configured.  If
    ``per_engine_caps_usd[engine]`` is unset or zero, treats as
    no-cap and returns within_cap=True.
    """
    status = check_engine_cap(
        engine, ledger_path=ledger_path, caps_config=caps_config,
    )
    if not status.within_cap:
        raise CapExceededError(status)
    return status


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
