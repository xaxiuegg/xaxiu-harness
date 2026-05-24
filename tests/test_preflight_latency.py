"""W11-PER-CHECK-LATENCY-OBSERVABILITY: tests for preflight latency telemetry.

Per readiness panel M15+M19: operator can't answer 'how slow is preflight
on average' without grepping logs.  Each preflight check already records
duration_ms; aggregate into rolling p50/p95 + surface in harness.

This module provides:
- record_run(results, ledger_path) — append to JSONL ledger
- latency_summary(ledger_path, since_hours, check_name) — p50/p95/p99/count
- latency_table(ledger_path) — human-friendly rendered table
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness import preflight_latency as pl
from harness.preflight import PreflightCheck


# -- record_run ---------------------------------------------------------


def test_record_run_appends_one_row_per_check(tmp_path):
    ledger = tmp_path / "preflight_latency.jsonl"
    results = [
        PreflightCheck(name="engine:kimi", severity="ok",
                       message="ok", duration_ms=350),
        PreflightCheck(name="git_clean", severity="ok",
                       message="clean", duration_ms=120),
    ]
    pl.record_run(results, ledger_path=ledger)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    names = {r["name"] for r in rows}
    assert names == {"engine:kimi", "git_clean"}


def test_record_run_includes_timestamp_severity_duration(tmp_path):
    ledger = tmp_path / "preflight_latency.jsonl"
    results = [PreflightCheck(name="t", severity="warn",
                               message="x", duration_ms=500)]
    pl.record_run(results, ledger_path=ledger)
    row = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert "timestamp" in row
    assert row["severity"] == "warn"
    assert row["duration_ms"] == 500
    # Parseable ISO-8601
    datetime.fromisoformat(row["timestamp"])


def test_record_run_creates_parent_directory(tmp_path):
    """ledger may be in coord/observer/ which might not exist yet."""
    ledger = tmp_path / "nested" / "dir" / "latency.jsonl"
    results = [PreflightCheck(name="t", severity="ok",
                               message="", duration_ms=10)]
    pl.record_run(results, ledger_path=ledger)
    assert ledger.exists()


def test_record_run_skips_zero_duration_checks(tmp_path):
    """duration_ms=0 means the check didn't actually time itself —
    don't pollute the percentile distribution with it."""
    ledger = tmp_path / "l.jsonl"
    results = [
        PreflightCheck(name="real_check", severity="ok",
                       message="", duration_ms=100),
        PreflightCheck(name="untimed", severity="ok",
                       message="", duration_ms=0),
    ]
    pl.record_run(results, ledger_path=ledger)
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    names = {r["name"] for r in rows}
    assert "real_check" in names
    assert "untimed" not in names


def test_record_run_empty_results_is_noop(tmp_path):
    """No checks → no file mutation (don't even create the ledger)."""
    ledger = tmp_path / "l.jsonl"
    pl.record_run([], ledger_path=ledger)
    assert not ledger.exists()


# -- latency_summary ----------------------------------------------------


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def test_latency_summary_empty_ledger_returns_zeros(tmp_path):
    ledger = tmp_path / "l.jsonl"
    ledger.write_text("", encoding="utf-8")
    summary = pl.latency_summary(ledger_path=ledger)
    assert summary["count"] == 0
    assert summary["p50"] == 0
    assert summary["p95"] == 0
    assert summary["per_check"] == {}


def test_latency_summary_missing_file_returns_zeros(tmp_path):
    """File doesn't exist at all — return zeros, don't raise."""
    summary = pl.latency_summary(ledger_path=tmp_path / "missing.jsonl")
    assert summary["count"] == 0


def test_latency_summary_single_entry_returns_that_value_for_all_pctiles(tmp_path):
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    _write_ledger(ledger, [{
        "timestamp": now, "name": "engine:kimi",
        "severity": "ok", "duration_ms": 500,
    }])
    summary = pl.latency_summary(ledger_path=ledger)
    assert summary["count"] == 1
    assert summary["p50"] == 500
    assert summary["p95"] == 500


def test_latency_summary_computes_p50_p95_p99(tmp_path):
    """1..100 ms; p50≈50, p95≈95, p99≈99."""
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    entries = [
        {"timestamp": now, "name": "n", "severity": "ok",
         "duration_ms": d}
        for d in range(1, 101)
    ]
    _write_ledger(ledger, entries)
    s = pl.latency_summary(ledger_path=ledger)
    assert s["count"] == 100
    # Allow ±2 ms slop from interpolation
    assert 48 <= s["p50"] <= 52
    assert 93 <= s["p95"] <= 97
    assert 97 <= s["p99"] <= 100


def test_latency_summary_per_check_breakdown(tmp_path):
    """Per-check stats are keyed by check name."""
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    entries = []
    # engine:kimi has 10 fast runs
    for d in [100, 110, 120, 130, 140, 150, 160, 170, 180, 200]:
        entries.append({"timestamp": now, "name": "engine:kimi",
                         "severity": "ok", "duration_ms": d})
    # git_clean has 5 slow runs
    for d in [1000, 1100, 1200, 1300, 1500]:
        entries.append({"timestamp": now, "name": "git_clean",
                         "severity": "ok", "duration_ms": d})
    _write_ledger(ledger, entries)
    s = pl.latency_summary(ledger_path=ledger)
    per = s["per_check"]
    assert set(per.keys()) == {"engine:kimi", "git_clean"}
    assert per["engine:kimi"]["count"] == 10
    assert per["git_clean"]["count"] == 5
    # git_clean is meaningfully slower → reflects in p50
    assert per["git_clean"]["p50"] > per["engine:kimi"]["p50"]


def test_latency_summary_since_hours_filters_old_entries(tmp_path):
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=72)).isoformat()
    recent = (now - timedelta(minutes=10)).isoformat()
    entries = [
        {"timestamp": old, "name": "n", "severity": "ok", "duration_ms": 999},
        {"timestamp": recent, "name": "n", "severity": "ok", "duration_ms": 100},
    ]
    _write_ledger(ledger, entries)
    s = pl.latency_summary(ledger_path=ledger, since_hours=24.0)
    assert s["count"] == 1
    assert s["p50"] == 100  # old 999 excluded


def test_latency_summary_filters_by_check_name(tmp_path):
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    entries = [
        {"timestamp": now, "name": "engine:kimi",
         "severity": "ok", "duration_ms": 500},
        {"timestamp": now, "name": "git_clean",
         "severity": "ok", "duration_ms": 1500},
    ]
    _write_ledger(ledger, entries)
    s = pl.latency_summary(ledger_path=ledger, check_name="engine:kimi")
    assert s["count"] == 1
    assert s["p50"] == 500


def test_latency_summary_skips_malformed_lines(tmp_path):
    """Garbage lines shouldn't crash the aggregation."""
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    ledger.write_text(
        f'{{"timestamp": "{now}", "name": "n", "duration_ms": 100, '
        f'"severity": "ok"}}\n'
        f'not json garbage line\n'
        f'{{"missing": "fields"}}\n'
        f'{{"timestamp": "{now}", "name": "n", "duration_ms": 200, '
        f'"severity": "ok"}}\n',
        encoding="utf-8",
    )
    s = pl.latency_summary(ledger_path=ledger)
    # Only the two valid lines counted
    assert s["count"] == 2


# -- latency_table (human-readable) -------------------------------------


def test_latency_table_includes_headers(tmp_path):
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    _write_ledger(ledger, [{
        "timestamp": now, "name": "engine:kimi",
        "severity": "ok", "duration_ms": 350,
    }])
    text = pl.latency_table(ledger_path=ledger)
    # Operator-friendly column labels
    assert "check" in text.lower()
    assert "p50" in text.lower()
    assert "p95" in text.lower()
    assert "engine:kimi" in text


def test_latency_table_empty_ledger_says_so(tmp_path):
    text = pl.latency_table(ledger_path=tmp_path / "missing.jsonl")
    # Operator-readable empty state
    assert "no" in text.lower() or "empty" in text.lower()


def test_latency_table_sorts_by_p95_desc(tmp_path):
    """Slowest first — what the operator most needs to see."""
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    entries = []
    for d in [100, 110, 120]:
        entries.append({"timestamp": now, "name": "fast",
                         "severity": "ok", "duration_ms": d})
    for d in [800, 900, 1000]:
        entries.append({"timestamp": now, "name": "slow",
                         "severity": "ok", "duration_ms": d})
    _write_ledger(ledger, entries)
    text = pl.latency_table(ledger_path=ledger)
    # 'slow' appears before 'fast' in the text
    slow_pos = text.find("slow")
    fast_pos = text.find("fast")
    assert slow_pos != -1 and fast_pos != -1
    assert slow_pos < fast_pos


# -- size discipline (the agent polls this) -----------------------------


def test_latency_summary_payload_is_compact(tmp_path):
    """The agent SDK budget_status() embeds latency stats; keep them small."""
    ledger = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    entries = []
    for name in ["engine:kimi", "engine:deepseek", "engine:mimo",
                 "git_clean", "pytest_cache", "observer_armed",
                 "status_csv_fresh", "loops_armed"]:
        for d in range(100, 200):
            entries.append({"timestamp": now, "name": name,
                             "severity": "ok", "duration_ms": d})
    _write_ledger(ledger, entries)
    s = pl.latency_summary(ledger_path=ledger)
    serialized = json.dumps(s)
    # Whole summary including per-check breakdown < 2 KB
    assert len(serialized) < 2000, (
        f"latency summary {len(serialized)} bytes — too big"
    )
