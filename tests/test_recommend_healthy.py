"""W14-DISPATCH-HEALTH-AWARE-FALLBACK 2026-05-28: tests for the
health-aware recommender wrapper (Tier 1C of the engine-budget triad)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.engines.routing_recommend import (
    Recommendation,
    recommend,
    recommend_healthy,
)


def _seed_probe_log(path: Path, engine: str, category: str) -> None:
    """Append a single health-probe record to the jsonl log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": engine,
        "category": category,
        "source": "test",
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


class TestRecommendHealthy:
    def test_no_terminations_passes_through(
        self, tmp_path: Path,
    ) -> None:
        """No terminated engines → behaves identically to recommend()."""
        # Empty probe log
        log = tmp_path / "engine_health_probes.jsonl"
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        baseline = recommend("default")
        assert rec is not None
        # Same primary pick
        assert rec.engine == baseline.engine

    def test_missing_log_file_passes_through(
        self, tmp_path: Path,
    ) -> None:
        """Missing log file is not an error — treat as no terminations."""
        log = tmp_path / "nonexistent.jsonl"
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        assert rec is not None

    def test_skips_terminated_primary(self, tmp_path: Path) -> None:
        """If the primary pick is terminated, fall through to alternate."""
        log = tmp_path / "engine_health_probes.jsonl"
        baseline = recommend("default")  # e.g. mimo-via-claude
        # Find the underlying provider (mimo) and mark it terminated
        provider = baseline.engine.replace("-via-claude", "")
        _seed_probe_log(log, provider, "terminated")
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        assert rec is not None
        assert rec.engine != baseline.engine, (
            "should have fallen through to alternate"
        )
        # The fallback must not also be terminated
        fallback_provider = rec.engine.replace("-via-claude", "")
        assert fallback_provider != provider

    def test_returns_none_when_all_terminated(self, tmp_path: Path) -> None:
        """If every candidate is terminated, return None."""
        log = tmp_path / "engine_health_probes.jsonl"
        # Mark every Pattern B provider as terminated
        for prov in ("mimo", "deepseek", "kimi"):
            _seed_probe_log(log, prov, "terminated")
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        assert rec is None

    def test_exclude_still_applied(self, tmp_path: Path) -> None:
        """exclude= still works alongside health filtering."""
        log = tmp_path / "engine_health_probes.jsonl"
        baseline = recommend("default")
        rec = recommend_healthy(
            "default",
            exclude={baseline.engine},
            health_probe_log_path=log,
        )
        # Must not return the excluded primary
        assert rec is not None
        assert rec.engine != baseline.engine

    def test_pattern_b_provider_mapping(self, tmp_path: Path) -> None:
        """Marking provider `mimo` as terminated should skip the Pattern
        B engine `mimo-via-claude`, not require both names."""
        log = tmp_path / "engine_health_probes.jsonl"
        _seed_probe_log(log, "mimo", "terminated")
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        # Should NOT return mimo-via-claude even though the termination
        # was logged against the bare provider name
        assert rec is None or rec.engine != "mimo-via-claude"

    def test_audit_class_skips_terminated_auditor(
        self, tmp_path: Path,
    ) -> None:
        """recommend_healthy('audit', exclude={producer}) skips
        terminated auditors."""
        log = tmp_path / "engine_health_probes.jsonl"
        # Without termination, audit would pick deepseek-via-claude
        baseline = recommend("audit", exclude={"mimo-via-claude"})
        provider = baseline.engine.replace("-via-claude", "")
        # Now terminate that provider
        _seed_probe_log(log, provider, "terminated")
        rec = recommend_healthy(
            "audit",
            exclude={"mimo-via-claude"},
            health_probe_log_path=log,
        )
        if rec is not None:
            assert rec.engine != baseline.engine

    def test_non_terminated_recent_up_probe_does_not_block(
        self, tmp_path: Path,
    ) -> None:
        """A more recent 'up' probe AFTER a 'terminated' one should
        clear the engine from the terminated set (newest wins).
        Behavior inherited from _recently_terminated_engines."""
        import time
        log = tmp_path / "engine_health_probes.jsonl"
        baseline = recommend("default")
        provider = baseline.engine.replace("-via-claude", "")
        _seed_probe_log(log, provider, "terminated")
        time.sleep(0.01)  # ensure later timestamp
        _seed_probe_log(log, provider, "up")
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        # The 'up' probe is more recent → engine is healthy → pass through
        assert rec is not None
        assert rec.engine == baseline.engine
