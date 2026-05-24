"""W11-PER-CHECK-LATENCY-OBSERVABILITY: rolling latency telemetry for
preflight checks.

Each ``harness preflight`` run already records ``duration_ms`` per check.
This module:

  1. Persists each run to a JSONL ledger at coord/observer/preflight_latency.jsonl
  2. Aggregates into p50 / p95 / p99 / count, both overall and per-check
  3. Renders an operator-friendly table sorted by p95 desc (slowest first)

Why a ledger and not a sqlite table:
  - Operator can ``cat`` it to inspect
  - Zero schema migration risk
  - Atomic appends are safe under concurrent preflight runs
  - Stays small (~100 bytes/check x 8 checks x 10 runs/day = 8 KB/day)

The agent SDK polls this via budget_status() so the operator can ask
"is preflight slow today?" without grepping logs.  Hence the size
discipline (test: payload < 2 KB serialized).
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from harness.preflight import PreflightCheck


def _default_ledger_path() -> Path:
    """Default location: coord/observer/preflight_latency.jsonl, parallel
    to the dispatch ledger + observer state."""
    from harness._constants import _REPO_ROOT
    return _REPO_ROOT / "coord" / "observer" / "preflight_latency.jsonl"


# -- record -------------------------------------------------------------


def record_run(results: Iterable[PreflightCheck],
               ledger_path: Path | None = None,
               prune_older_than_days: int | None = 7) -> int:
    """Append one row per timed check to the ledger.  Returns # rows written.

    Skips checks with duration_ms=0 (untimed; would pollute percentiles).
    Empty input is a no-op (no file created).

    W11 audit fix (K01/K07/K10): when ``prune_older_than_days`` is set
    (default 7), entries older than that cutoff are dropped before the
    new rows are written.  Keeps the JSONL bounded so percentile
    computation stays O(recent-window) rather than O(all-time).  Set
    to None to disable pruning (tests + audit retention scenarios).
    """
    if ledger_path is None:
        ledger_path = _default_ledger_path()
    rows: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for r in results:
        if r.duration_ms <= 0:
            continue
        rows.append({
            "timestamp": now_iso,
            "name": r.name,
            "severity": r.severity,
            "duration_ms": r.duration_ms,
        })
    if not rows:
        return 0
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    # W11 audit fix (K01/K07/K10): prune in-place before appending.
    if prune_older_than_days is not None and ledger_path.exists():
        try:
            prune_old_entries(ledger_path,
                              max_age_days=prune_older_than_days)
        except OSError:
            # Pruning failure is non-fatal; we still want the new rows
            # to land.  The ledger may not exist after a failed prune,
            # which is fine (open(..., "a") will recreate).
            pass
    with ledger_path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return len(rows)


def prune_old_entries(ledger_path: Path,
                       max_age_days: int = 7) -> int:
    """Drop entries older than ``max_age_days`` from the ledger.

    Returns the number of rows removed.  Atomic via temp-file rename
    so a kill mid-prune leaves the original intact.
    """
    if not ledger_path.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    kept: list[str] = []
    removed = 0
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            ts_raw = row.get("timestamp")
            if not isinstance(ts_raw, str):
                kept.append(line)  # malformed → keep (don't lose data)
                continue
            ts = _parse_ts(ts_raw)
            if ts is None or ts >= cutoff:
                kept.append(line)
            else:
                removed += 1
        except json.JSONDecodeError:
            kept.append(line)  # keep malformed; aggregator skips it
    if removed == 0:
        return 0
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""),
                    encoding="utf-8")
    tmp.replace(ledger_path)
    return removed


# -- summary ------------------------------------------------------------


def _parse_ts(s: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _load_ledger(ledger_path: Path,
                  since_hours: float | None,
                  check_name: str | None) -> list[dict]:
    """Yield rows passing the time + name filter.  Skips malformed lines."""
    if not ledger_path.exists():
        return []
    cutoff: datetime | None = None
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    out: list[dict] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if "duration_ms" not in row or "name" not in row \
                or "timestamp" not in row:
            continue
        if not isinstance(row["duration_ms"], (int, float)):
            continue
        if check_name is not None and row["name"] != check_name:
            continue
        ts = _parse_ts(row["timestamp"])
        if cutoff is not None and (ts is None or ts < cutoff):
            continue
        out.append(row)
    return out


def _pctile(values: list[float], p: float) -> int:
    """Return the p-th percentile (0..100) as int ms.

    Uses the inclusive linear-interpolation method (Python's
    statistics.quantiles with method='inclusive' is N=100 for 99
    cut-points; we want a single p so we do it directly).
    """
    if not values:
        return 0
    if len(values) == 1:
        return int(round(values[0]))
    s = sorted(values)
    # 0-indexed position in [0, n-1]
    pos = (p / 100.0) * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return int(round(s[lo] + (s[hi] - s[lo]) * frac))


def latency_summary(ledger_path: Path | None = None,
                     since_hours: float | None = None,
                     check_name: str | None = None) -> dict:
    """Return aggregate latency stats.

    Shape:
        {
            "count": int,
            "p50": int,        # ms
            "p95": int,        # ms
            "p99": int,        # ms
            "mean": int,       # ms
            "max": int,        # ms
            "window_hours": float | None,
            "per_check": {
                "<name>": {"count": int, "p50": int, "p95": int, "max": int},
                ...
            },
        }
    """
    if ledger_path is None:
        ledger_path = _default_ledger_path()
    rows = _load_ledger(ledger_path, since_hours, check_name)
    if not rows:
        return {"count": 0, "p50": 0, "p95": 0, "p99": 0,
                "mean": 0, "max": 0,
                "window_hours": since_hours, "per_check": {}}
    overall = [float(r["duration_ms"]) for r in rows]
    by_name: dict[str, list[float]] = {}
    for r in rows:
        by_name.setdefault(r["name"], []).append(float(r["duration_ms"]))
    per_check: dict[str, dict] = {}
    for name, vals in by_name.items():
        per_check[name] = {
            "count": len(vals),
            "p50": _pctile(vals, 50),
            "p95": _pctile(vals, 95),
            "max": int(round(max(vals))),
        }
    return {
        "count": len(overall),
        "p50": _pctile(overall, 50),
        "p95": _pctile(overall, 95),
        "p99": _pctile(overall, 99),
        "mean": int(round(statistics.fmean(overall))),
        "max": int(round(max(overall))),
        "window_hours": since_hours,
        "per_check": per_check,
    }


# -- rendered table -----------------------------------------------------


def latency_table(ledger_path: Path | None = None,
                   since_hours: float | None = None,
                   check_name: str | None = None) -> str:
    """Render an operator-friendly table sorted by p95 desc (slowest first).

    W11 audit fix (K03): ``check_name`` filter now flows through the
    pretty path too (was previously honored only by --format json).
    """
    s = latency_summary(ledger_path=ledger_path, since_hours=since_hours,
                         check_name=check_name)
    if s["count"] == 0:
        return ("No preflight latency samples recorded yet.\n"
                "Run `harness preflight` to populate the ledger.")
    per = s["per_check"]
    ordered = sorted(per.items(), key=lambda kv: kv[1]["p95"], reverse=True)
    lines: list[str] = []
    window = (
        f" (last {s['window_hours']}h)" if s["window_hours"] is not None
        else " (all-time)"
    )
    lines.append(f"Preflight latency{window} — {s['count']} samples")
    lines.append("")
    lines.append(f"  {'check':<28} {'n':>5}  {'p50':>7}  {'p95':>7}  {'max':>7}")
    lines.append(f"  {'-' * 28} {'-' * 5}  {'-' * 7}  {'-' * 7}  {'-' * 7}")
    for name, st in ordered:
        lines.append(
            f"  {name:<28} {st['count']:>5}  "
            f"{st['p50']:>5}ms  {st['p95']:>5}ms  {st['max']:>5}ms"
        )
    lines.append("")
    lines.append(
        f"Overall: p50={s['p50']}ms  p95={s['p95']}ms  "
        f"p99={s['p99']}ms  max={s['max']}ms"
    )
    return "\n".join(lines)
