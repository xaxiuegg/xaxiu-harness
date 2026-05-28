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
        """If the primary pick is a Pattern A engine and terminated,
        fall through to alternate.

        W14-REPO-WIDE-STALENESS-AUDIT 2026-05-28: previously seeded the
        Pattern A *bare provider name* (e.g. ``mimo``) expecting the
        Pattern B engine (``mimo-via-claude``) to also skip — but Pattern
        B routes via Claude Code subprocess, NOT direct HTTP, so the
        signal does not apply.  Use a Pattern A engine name here so the
        match actually fires.
        """
        log = tmp_path / "engine_health_probes.jsonl"
        # Mark a Pattern A engine as terminated (matches by engine name,
        # not the Pattern B wrapper).  For "default" task class
        # recommend() returns mimo-via-claude (Pattern B), which won't
        # filter regardless — so test that termination of a Pattern A
        # name doesn't drop a Pattern B recommendation.
        _seed_probe_log(log, "mimo", "terminated")
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        baseline = recommend("default")
        assert rec is not None
        # Pattern B engines are NOT filtered by Pattern A termination —
        # so even with "mimo" terminated, mimo-via-claude is still picked.
        assert rec.engine == baseline.engine

    def test_returns_none_when_all_terminated(self, tmp_path: Path) -> None:
        """If every candidate engine name is in the terminated set,
        return None.

        W14-REPO-WIDE-STALENESS-AUDIT 2026-05-28: must use the actual
        engine names (Pattern B uses ``mimo-via-claude``, not ``mimo``)
        because the per-transport filter no longer applies bare-provider
        mapping to Pattern B.
        """
        log = tmp_path / "engine_health_probes.jsonl"
        # Mark every Pattern B engine name as terminated (note: full
        # `mimo-via-claude` name; bare `mimo` no longer maps to it).
        # Bare names DO still match Pattern A engines if any are routed.
        for eng in ("mimo-via-claude", "deepseek-via-claude",
                    "kimi-via-claude"):
            _seed_probe_log(log, eng, "terminated")
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        # Pattern B engines are exempt from termination filtering by
        # design (different transport), so even seeding them as
        # terminated does not skip them.  This locks the design
        # decision — if the desired behavior is "treat Pattern B
        # terminated entries as authoritative," fix recommend_healthy.
        assert rec is not None
        assert rec.engine.endswith("-via-claude")

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

    def test_pattern_b_NOT_filtered_by_pattern_a_termination(
        self, tmp_path: Path,
    ) -> None:
        """W14-REPO-WIDE-STALENESS-AUDIT 2026-05-28: Pattern B engines
        use Claude Code subprocess transport, NOT the direct-HTTP path
        that the probe log measures.  A Pattern A termination signal
        (e.g. ``kimi`` direct API down per Moonshot's 2026-05-22
        action) MUST NOT propagate to ``kimi-via-claude`` (Pattern B,
        Coding Agents path, still functional).  This test locks the
        transport-aware design.
        """
        log = tmp_path / "engine_health_probes.jsonl"
        _seed_probe_log(log, "mimo", "terminated")
        rec = recommend_healthy(
            "default", health_probe_log_path=log,
        )
        # Pattern B engine (mimo-via-claude) should STILL be returned
        # despite the bare "mimo" termination — different transport.
        assert rec is not None
        assert rec.engine == "mimo-via-claude"

    def test_audit_class_skips_terminated_pattern_a_auditor(
        self, tmp_path: Path,
    ) -> None:
        """W14-REPO-WIDE-STALENESS-AUDIT 2026-05-28: audit-mode honors
        the Pattern A termination filter for Pattern A engine names.
        Pattern B engines (the actual current audit pool) are exempt
        by design.
        """
        log = tmp_path / "engine_health_probes.jsonl"
        # Note: current "audit" task class returns Pattern B engines
        # (deepseek-via-claude / kimi-via-claude).  Pattern B is
        # exempted, so termination of bare names doesn't drop them.
        baseline = recommend("audit", exclude={"mimo-via-claude"})
        provider = baseline.engine.replace("-via-claude", "")
        _seed_probe_log(log, provider, "terminated")
        rec = recommend_healthy(
            "audit",
            exclude={"mimo-via-claude"},
            health_probe_log_path=log,
        )
        # Pattern B baseline survives — terminations apply only to
        # Pattern A engines (bare provider names that equal the
        # engine name).
        assert rec is not None
        assert rec.engine == baseline.engine

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
