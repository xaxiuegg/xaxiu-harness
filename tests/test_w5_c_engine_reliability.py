"""W5-C: engine reliability digest aggregated from W4-G campaign data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.engines.reliability import (
    EngineReliabilityRow, aggregate_campaigns, load_published, publish,
)


def _seed_campaign(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at_utc": "2026-05-22T00:00:00+00:00",
        "total_agents": len(results),
        "ok": sum(1 for r in results if r.get("success")),
        "results": results,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_aggregate_campaigns_empty_dir_no_results(tmp_path: Path) -> None:
    digest = aggregate_campaigns(coverage_dir=tmp_path / "absent")
    assert digest.ranking == []
    assert "no coverage" in digest.notes.lower()


def test_aggregate_campaigns_no_campaign_files(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage"
    coverage.mkdir()
    digest = aggregate_campaigns(coverage_dir=coverage)
    assert digest.ranking == []
    assert "no campaign files" in digest.notes.lower()


def test_aggregate_campaigns_buckets_by_engine_model(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage"
    _seed_campaign(coverage / "multi_agent_campaign_a.json", [
        {"engine": "deepseek", "model": "deepseek-v4-flash",
         "success": True, "latency_ms": 1000},
        {"engine": "deepseek", "model": "deepseek-v4-flash",
         "success": True, "latency_ms": 2000},
        {"engine": "kimi", "model": "kimi-for-coding",
         "success": False, "latency_ms": 5000},
    ])
    digest = aggregate_campaigns(coverage_dir=coverage)
    assert len(digest.ranking) == 2
    # Sort: deepseek (100%) first
    assert digest.ranking[0].engine == "deepseek"
    assert digest.ranking[0].ok == 2
    assert digest.ranking[0].fail == 0
    assert digest.ranking[0].parseable_rate == 1.0
    assert digest.ranking[1].engine == "kimi"
    assert digest.ranking[1].parseable_rate == 0.0


def test_aggregate_campaigns_merges_multiple_files(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage"
    _seed_campaign(coverage / "multi_agent_campaign_a.json", [
        {"engine": "deepseek", "model": "x", "success": True, "latency_ms": 100},
    ])
    _seed_campaign(coverage / "multi_agent_campaign_b.json", [
        {"engine": "deepseek", "model": "x", "success": False, "latency_ms": 200},
    ])
    digest = aggregate_campaigns(coverage_dir=coverage)
    assert len(digest.source_campaigns) == 2
    assert digest.ranking[0].ok == 1
    assert digest.ranking[0].fail == 1
    assert digest.ranking[0].parseable_rate == 0.5


def test_aggregate_campaigns_skips_unparseable_json(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage"
    coverage.mkdir()
    (coverage / "multi_agent_campaign_bad.json").write_text("not json", encoding="utf-8")
    _seed_campaign(coverage / "multi_agent_campaign_good.json", [
        {"engine": "deepseek", "model": "x", "success": True, "latency_ms": 100},
    ])
    digest = aggregate_campaigns(coverage_dir=coverage)
    # Bad file is silently skipped; good file produces one ranking row
    assert len(digest.ranking) == 1


def test_publish_and_load(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage"
    _seed_campaign(coverage / "multi_agent_campaign_x.json", [
        {"engine": "mimo", "model": "mimo-v2.5", "success": True, "latency_ms": 500},
        {"engine": "mimo", "model": "mimo-v2.5", "success": False, "latency_ms": 700},
    ])
    out = tmp_path / "out" / "reliability.json"
    written = publish(coverage_dir=coverage, out_path=out)
    assert written == out
    assert out.exists()

    loaded = load_published(out)
    assert loaded is not None
    assert len(loaded.ranking) == 1
    assert loaded.ranking[0].engine == "mimo"
    assert loaded.ranking[0].parseable_rate == 0.5


def test_load_published_missing_returns_none(tmp_path: Path) -> None:
    assert load_published(tmp_path / "absent.json") is None


def test_load_published_corrupt_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("definitely not json", encoding="utf-8")
    assert load_published(path) is None


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_cli_engines_reliability_no_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 1 with friendly message when no campaign data exists."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-reliability"])
    assert result.exit_code == 1
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "no reliability data" in combined.lower()


def test_cli_engines_reliability_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["engines-reliability", "--help"])
    assert result.exit_code == 0
    assert "--publish" in result.output
    assert "fallback-time" in result.output.lower() or "fallback" in result.output.lower()
