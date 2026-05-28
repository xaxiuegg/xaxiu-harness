"""W14-ASK-HISTORY 2026-05-28 (Phase 2.3 of agentic-operator roadmap):
list + render past `harness ask` outputs.

Pairs naturally with `harness ask --rerun <dir>` (Phase 2.2): history
gives you a dir id; rerun reuses it.  Operators previously had to open
File Explorer + navigate `coord/reviews/` to find past asks — these
verbs make the forever-record queryable from the CLI.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _reviews_dir() -> Path:
    """Default location of saved ask outputs."""
    here = Path(__file__).resolve()
    return here.parents[2] / "coord" / "reviews"


def _read_ask_summary(ask_dir: Path) -> Dict[str, Any]:
    """Read summary.json from an ask-* dir.  Returns a dict with at
    minimum an ``id`` field; other fields are best-effort.

    Older asks may have missing or partial summary.json — we surface
    what we can find.
    """
    row: Dict[str, Any] = {
        "id": ask_dir.name,
        "path": str(ask_dir),
        "mode": "?",
        "question": "",
        "engines": [],
        "total_cost_usd": None,
        "max_latency_s": None,
        "timestamp": "",
        "verdict": None,
        "parent_id": None,
    }
    summary = ask_dir / "summary.json"
    if not summary.exists():
        return row
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return row
    row["mode"] = data.get("mode", "?")
    row["question"] = data.get("question", "")
    row["engines"] = [
        r.get("engine") for r in data.get("results", [])
        if r.get("engine")
    ]
    row["total_cost_usd"] = data.get("total_cost_usd")
    row["max_latency_s"] = data.get("max_latency_s")
    row["timestamp"] = data.get("timestamp", "")
    row["parent_id"] = data.get("parent_id")
    v = data.get("verdict")
    if isinstance(v, dict):
        row["verdict"] = v.get("verdict")
    return row


def list_asks(
    reviews_dir: Optional[Path] = None,
    last_n: int = 20,
    mode_filter: Optional[str] = None,
    verdict_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List past ask-* directories under ``reviews_dir``.

    Returns newest-first by directory name (ids are timestamped).
    ``mode_filter`` keeps only matching ``mode`` rows.
    ``verdict_filter`` keeps only matching ``verdict.verdict`` rows
    (use ``"PASS"``, ``"PARTIAL"``, ``"FAIL"``, ``"UNKNOWN"``).
    ``last_n`` caps the result count (None or 0 → no cap).
    """
    base = reviews_dir or _reviews_dir()
    if not base.exists():
        return []
    dirs = sorted(
        [d for d in base.glob("ask-*") if d.is_dir()],
        reverse=True,
    )
    rows: List[Dict[str, Any]] = []
    for d in dirs:
        row = _read_ask_summary(d)
        if mode_filter and row["mode"] != mode_filter:
            continue
        if verdict_filter and (row["verdict"] or "").upper() != verdict_filter.upper():
            continue
        rows.append(row)
        if last_n and len(rows) >= last_n:
            break
    return rows


def render_history_text(rows: List[Dict[str, Any]]) -> str:
    """Render the history list as a fixed-width table.

    Columns: id (timestamp), mode, verdict, engines, cost, question excerpt.
    """
    if not rows:
        return "(no asks found in coord/reviews/)\n"

    lines: List[str] = []
    header = (
        f"{'id':<46} {'mode':<8} {'verdict':<10} {'cost':<10} question"
    )
    lines.append(header)
    lines.append("-" * 110)
    for r in rows:
        verdict = r.get("verdict") or ""
        cost = (
            f"${r['total_cost_usd']:.4f}"
            if r.get("total_cost_usd") is not None else "—"
        )
        q_excerpt = (r.get("question") or "").replace("\n", " ")[:60]
        lines.append(
            f"  {r['id']:<44} {r['mode']:<8} {verdict:<10} "
            f"{cost:<10} {q_excerpt}"
        )
    lines.append("")
    return "\n".join(lines)


def load_ask(
    ask_id: str,
    reviews_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load full data for one ask: question, per-engine files, summary.

    Returns a dict with: ``id``, ``path``, ``question``, ``summary``
    (full summary.json content), ``per_engine`` (dict of filename →
    content for every <engine>.md / producer-*.md / audit-*.md),
    ``packet`` (packet.md content if present), ``error`` (if not
    found).
    """
    base = reviews_dir or _reviews_dir()
    ask_dir = base / ask_id
    if not ask_dir.exists() or not ask_dir.is_dir():
        return {"id": ask_id, "error": f"directory not found: {ask_dir}"}

    result: Dict[str, Any] = {
        "id": ask_id,
        "path": str(ask_dir),
        "question": "",
        "summary": {},
        "per_engine": {},
        "packet": "",
    }

    q_file = ask_dir / "question.md"
    if q_file.exists():
        raw = q_file.read_text(encoding="utf-8").strip()
        # Strip the "# Panel question" header to surface just the question
        if raw.startswith("# Panel question") and "\n\n" in raw:
            raw = raw.split("\n\n", 1)[1]
        result["question"] = raw.strip()

    summary = ask_dir / "summary.json"
    if summary.exists():
        try:
            result["summary"] = json.loads(
                summary.read_text(encoding="utf-8"),
            )
        except (json.JSONDecodeError, OSError):
            pass

    # All .md files except question.md + packet.md become per-engine
    for f in sorted(ask_dir.glob("*.md")):
        if f.name in ("question.md", "packet.md"):
            continue
        result["per_engine"][f.name] = f.read_text(encoding="utf-8")

    packet = ask_dir / "packet.md"
    if packet.exists():
        result["packet"] = packet.read_text(encoding="utf-8")

    return result


def render_ask_text(data: Dict[str, Any]) -> str:
    """Render one ask as human-readable text: question, mode, engines,
    verdict (if audit), per-engine responses."""
    if "error" in data:
        return f"ERROR: {data['error']}\n"

    lines: List[str] = []
    s = data.get("summary") or {}

    lines.append(f"# {data['id']}")
    lines.append(f"path: {data['path']}")
    mode = s.get("mode", "?")
    lines.append(f"mode: {mode}")
    if s.get("timestamp"):
        lines.append(f"timestamp: {s['timestamp']}")
    if s.get("parent_id"):
        lines.append(f"parent_id: {s['parent_id']} (this is a rerun)")
    if s.get("total_cost_usd") is not None:
        lines.append(f"total_cost: ${s['total_cost_usd']:.4f}")

    # Question
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append(data.get("question", "(no question.md)"))

    # Audit verdict
    v = s.get("verdict")
    if isinstance(v, dict):
        lines.append("")
        lines.append("## Verdict")
        lines.append("")
        lines.append(f"VERDICT: {v.get('verdict', 'UNKNOWN')}")
        if v.get("summary"):
            lines.append(f"ONE-LINE: {v['summary']}")
        if v.get("corrections"):
            lines.append(f"CORRECTIONS: {v['corrections']}")
        if v.get("missed"):
            lines.append(f"MISSED: {v['missed']}")
        if v.get("overall"):
            lines.append(f"OVERALL: {v['overall']}")

    # Per-engine responses
    if data.get("per_engine"):
        lines.append("")
        lines.append("## Per-engine responses")
        for fname, content in sorted(data["per_engine"].items()):
            lines.append("")
            lines.append(f"### {fname}")
            lines.append("")
            lines.append(content.rstrip())

    lines.append("")
    return "\n".join(lines)
