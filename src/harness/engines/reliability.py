"""W5-C: engine reliability tier auto-published from campaign data.

Reads any `coord/coverage/multi_agent_campaign_*.json` files, aggregates
parseable% per engine, and writes a digest at
``coord/engine_reliability.json`` that the dispatcher can consult to
order its fallback chain by historical reliability.

This is *observational* metadata — the dispatcher still tries the
operator-specified engine first.  When that engine fails AND fallback
triggers, we prefer the most-reliable available engine instead of the
hardcoded chain (deepseek -> kimi -> anthropic -> gemini).

The function is deliberately simple: bucket dispatches by engine,
compute parseable_rate = ok / (ok + fail), and emit a sorted ranking.
Operator can override by deleting the file -- dispatcher falls back to
the hardcoded chain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class EngineReliabilityRow:
    engine: str
    model: str | None
    ok: int
    fail: int
    parseable_rate: float  # ok / (ok + fail), 0.0–1.0
    avg_latency_ms: int


@dataclass(frozen=True)
class ReliabilityDigest:
    generated_at: str         # ISO-8601 UTC
    source_campaigns: list[str]  # campaign filenames
    ranking: list[EngineReliabilityRow]
    notes: str = ""


def aggregate_campaigns(
    coverage_dir: Path | None = None,
) -> ReliabilityDigest:
    """Read all campaign JSON files and emit a reliability digest.

    Args:
        coverage_dir: Directory holding ``multi_agent_campaign_*.json``
            files.  Defaults to ``coord/coverage/`` relative to cwd.
    """
    coverage_dir = coverage_dir or Path("coord/coverage")
    if not coverage_dir.exists():
        return ReliabilityDigest(
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_campaigns=[],
            ranking=[],
            notes="no coverage directory found; ranking empty",
        )

    # Glob both W4-G campaigns AND W5-F source-laden verifications.  Both
    # have the same `results` array shape ({engine, model, success,
    # latency_ms, ...}) so they aggregate cleanly.  The verification runs
    # include budget context that updates the empirical picture as new
    # data lands (e.g. MiMo Pro at 8192-token budget = 3/3, not the W4-G
    # 2/5).
    campaigns = sorted(
        list(coverage_dir.glob("multi_agent_campaign_*.json"))
        + list(coverage_dir.glob("verify_source_laden_*.json"))
    )
    if not campaigns:
        return ReliabilityDigest(
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_campaigns=[],
            ranking=[],
            notes="no campaign files yet; run scripts/multi_agent_coverage.py first",
        )

    # Bucket by (engine, model)
    buckets: dict[tuple[str, str], dict[str, int]] = {}
    for cp in campaigns:
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for r in data.get("results", []):
            key = (str(r.get("engine", "?")), str(r.get("model", "?")))
            agg = buckets.setdefault(key, {"ok": 0, "fail": 0, "latency_sum": 0,
                                          "count": 0})
            if r.get("success"):
                agg["ok"] += 1
            else:
                agg["fail"] += 1
            agg["latency_sum"] += int(r.get("latency_ms", 0))
            agg["count"] += 1

    ranking: list[EngineReliabilityRow] = []
    for (engine, model), agg in buckets.items():
        total = agg["ok"] + agg["fail"]
        rate = agg["ok"] / total if total else 0.0
        avg_lat = agg["latency_sum"] // agg["count"] if agg["count"] else 0
        ranking.append(EngineReliabilityRow(
            engine=engine, model=model,
            ok=agg["ok"], fail=agg["fail"],
            parseable_rate=round(rate, 3),
            avg_latency_ms=avg_lat,
        ))

    # Sort: most reliable first; tiebreak by lower latency
    ranking.sort(key=lambda r: (-r.parseable_rate, r.avg_latency_ms))

    return ReliabilityDigest(
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_campaigns=[c.name for c in campaigns],
        ranking=ranking,
        notes=f"aggregated {len(campaigns)} campaign(s); "
              f"{sum(b['ok']+b['fail'] for b in buckets.values())} total dispatches",
    )


def publish(
    coverage_dir: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    """Generate digest and write to coord/engine_reliability.json.

    Returns the path written.
    """
    digest = aggregate_campaigns(coverage_dir)
    out_path = out_path or Path("coord/engine_reliability.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Convert dataclasses to dicts for JSON serialization
    payload = {
        "generated_at": digest.generated_at,
        "source_campaigns": digest.source_campaigns,
        "notes": digest.notes,
        "ranking": [asdict(r) for r in digest.ranking],
    }
    # W9-STATE-ATOMIC-WRITES 2026-05-24: was a raw write_text +
    # json.dumps which could leave the file half-written on crash.
    # Now routes through the canonical atomic helper.
    from harness.state.files import atomic_write_json
    atomic_write_json(out_path, payload, set_mode_0600=False)
    return out_path


def load_published(
    path: Path | None = None,
) -> ReliabilityDigest | None:
    """Read the published digest, or return None if missing/corrupt.

    Used by the dispatcher to query reliability at fallback time.
    """
    path = path or Path("coord/engine_reliability.json")
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    try:
        ranking = [EngineReliabilityRow(**r) for r in raw.get("ranking", [])]
        return ReliabilityDigest(
            generated_at=str(raw.get("generated_at", "")),
            source_campaigns=list(raw.get("source_campaigns", [])),
            ranking=ranking,
            notes=str(raw.get("notes", "")),
        )
    except (TypeError, ValueError):
        return None
