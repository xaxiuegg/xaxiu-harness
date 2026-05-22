"""W5-D: `harness budget by-run` cost-per-run rollup.

Groups ledger entries by task_id (which is the coord run-id for worker-
spawned dispatches per W3-B convention) and surfaces tokens + cost per
run, sorted by most-expensive.  Lets the operator answer 'did this
overnight run blow my budget' in one command.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli


def _seed_ledger(path: Path, rows: list[dict]) -> None:
    """Write JSONL ledger entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_budget_by_run_help_advertises_purpose() -> None:
    """Help text should mention W4-K token tracking + overnight-budget question."""
    runner = CliRunner()
    result = runner.invoke(cli, ["budget", "by-run", "--help"])
    assert result.exit_code == 0
    assert "Per-run cost rollup" in result.output
    assert "--top" in result.output
    assert "--since" in result.output


def test_budget_by_run_groups_by_task_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two dispatches sharing the same task_id should aggregate into one row."""
    ledger = tmp_path / "budget_ledger.jsonl"
    now_iso = datetime.now(timezone.utc).isoformat()
    _seed_ledger(ledger, [
        {"timestamp": now_iso, "task_id": "run-A", "engine": "deepseek",
         "model": "deepseek-v4-flash", "input_tokens": 100,
         "output_tokens": 200, "latency_ms": 100, "cost_usd": 0.0010},
        {"timestamp": now_iso, "task_id": "run-A", "engine": "deepseek",
         "model": "deepseek-v4-flash", "input_tokens": 50,
         "output_tokens": 75, "latency_ms": 50, "cost_usd": 0.0005},
        {"timestamp": now_iso, "task_id": "run-B", "engine": "kimi",
         "model": "kimi-for-coding", "input_tokens": 30,
         "output_tokens": 40, "latency_ms": 200, "cost_usd": 0.0002},
    ])
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)

    runner = CliRunner()
    result = runner.invoke(cli, ["budget", "by-run", "--since-days", "1"])
    assert result.exit_code == 0, result.output
    # run-A should aggregate 2 dispatches with tokens 150/275 and cost ~0.0015
    assert "run-A" in result.output
    assert "run-B" in result.output
    # run-A is more expensive so it appears first in the sort order
    assert result.output.index("run-A") < result.output.index("run-B")


def test_budget_by_run_top_limits_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--top N caps the visible rows."""
    ledger = tmp_path / "budget_ledger.jsonl"
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = [{
        "timestamp": now_iso, "task_id": f"run-{i}", "engine": "deepseek",
        "model": "deepseek-v4-flash", "input_tokens": 10, "output_tokens": 10,
        "latency_ms": 10, "cost_usd": float(i) * 0.001,
    } for i in range(1, 6)]
    _seed_ledger(ledger, rows)
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)

    runner = CliRunner()
    result = runner.invoke(cli, ["budget", "by-run", "--since-days", "1", "--top", "2"])
    assert result.exit_code == 0, result.output
    # Should show top 2 (run-5, run-4) and mention 3 more not shown
    assert "run-5" in result.output
    assert "run-4" in result.output
    assert "3 more runs not shown" in result.output


def test_budget_by_run_no_dispatches_in_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty range should print friendly '(no dispatches in range)' and exit 0."""
    ledger = tmp_path / "budget_ledger.jsonl"
    # Old entry, before our since window
    _seed_ledger(ledger, [{
        "timestamp": "2020-01-01T00:00:00+00:00", "task_id": "ancient",
        "engine": "deepseek", "model": None, "input_tokens": 0,
        "output_tokens": 0, "latency_ms": 0, "cost_usd": 0.0,
    }])
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", ledger)

    runner = CliRunner()
    result = runner.invoke(cli, ["budget", "by-run", "--since-days", "1"])
    assert result.exit_code == 0
    assert "no dispatches in range" in result.output


def test_budget_by_run_mutually_exclusive_since_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--since and --since-days together should reject cleanly."""
    monkeypatch.setattr("harness.cli.DEFAULT_LEDGER_PATH", tmp_path / "missing.jsonl")
    runner = CliRunner()
    result = runner.invoke(cli, ["budget", "by-run",
                                  "--since-days", "1",
                                  "--since", "2026-01-01T00:00:00Z"])
    assert result.exit_code != 0
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "mutually exclusive" in combined.lower()
