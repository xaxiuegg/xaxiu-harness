"""Tests for harness.session.recommender — exact threshold logic."""

from __future__ import annotations

import pytest

from harness.session.recommender import SOFT_SIGNALS, Recommendation, recommend
from harness.session.signals import Signals


def _sig(**overrides: object) -> Signals:
    defaults = {
        "session_age_hours": 0.0,
        "tick_count": 0,
        "active_dispatch_count": 0,
        "commits_since_session": 0,
        "status_csv_row_count": 0,
        "mem_pct": 0.0,
        "claude_rss_mb": 0,
        "cpu_pct": 0.0,
        "disk_pct_free": 100.0,
        "jsonl_log_mb": 0.0,
    }
    defaults.update(overrides)  # type: ignore[typeddict-item]
    return Signals(**defaults)  # type: ignore[arg-type]


class TestThresholds:
    def test_none(self) -> None:
        rec, reasons = recommend(_sig())
        assert rec == Recommendation.NONE
        assert reasons == []

    def test_soft_by_age(self) -> None:
        rec, reasons = recommend(_sig(session_age_hours=4.1))
        assert rec == Recommendation.SOFT
        assert any("4.1h" in r for r in reasons)

    def test_soft_by_three_soft_signals(self) -> None:
        rec, reasons = recommend(
            _sig(
                tick_count=51,
                commits_since_session=31,
                status_csv_row_count=21,
            )
        )
        assert rec == Recommendation.SOFT
        assert any("soft" in r.lower() for r in reasons)

    def test_soft_by_exactly_three(self) -> None:
        rec, reasons = recommend(
            _sig(
                tick_count=51,
                commits_since_session=31,
                jsonl_log_mb=51,
            )
        )
        assert rec == Recommendation.SOFT

    def test_soft_two_only(self) -> None:
        rec, _ = recommend(
            _sig(
                tick_count=51,
                commits_since_session=31,
                session_age_hours=2.0,
            )
        )
        assert rec == Recommendation.NONE

    def test_strongly_by_mem(self) -> None:
        rec, reasons = recommend(_sig(mem_pct=85.0))
        assert rec == Recommendation.STRONGLY
        assert any("85.0%" in r for r in reasons)

    def test_strongly_by_rss(self) -> None:
        rec, reasons = recommend(_sig(claude_rss_mb=2049))
        assert rec == Recommendation.STRONGLY
        assert any("2049 MB" in r for r in reasons)

    def test_strongly_trumps_soft(self) -> None:
        rec, _ = recommend(
            _sig(
                session_age_hours=10.0,
                mem_pct=90.0,
            )
        )
        assert rec == Recommendation.STRONGLY

    def test_critical_by_mem(self) -> None:
        rec, reasons = recommend(_sig(mem_pct=95.0))
        assert rec == Recommendation.CRITICAL
        assert any("95.0%" in r for r in reasons)

    def test_critical_by_disk(self) -> None:
        rec, reasons = recommend(_sig(disk_pct_free=4.9))
        assert rec == Recommendation.CRITICAL
        assert any("4.9%" in r for r in reasons)

    def test_critical_trumps_all(self) -> None:
        rec, _ = recommend(
            _sig(
                mem_pct=95.0,
                disk_pct_free=4.0,
                session_age_hours=10.0,
                claude_rss_mb=3000,
            )
        )
        assert rec == Recommendation.CRITICAL

    def test_exactly_95_mem(self) -> None:
        rec, _ = recommend(_sig(mem_pct=95))
        assert rec == Recommendation.CRITICAL

    def test_exactly_85_mem(self) -> None:
        rec, _ = recommend(_sig(mem_pct=85))
        assert rec == Recommendation.STRONGLY

    def test_exactly_2048_rss_not_strongly(self) -> None:
        rec, _ = recommend(_sig(claude_rss_mb=2048))
        assert rec == Recommendation.NONE

    def test_exactly_5_disk_free_not_critical(self) -> None:
        rec, _ = recommend(_sig(disk_pct_free=5.0))
        assert rec == Recommendation.NONE

    def test_soft_reasons_content(self) -> None:
        rec, reasons = recommend(
            _sig(
                tick_count=100,
                commits_since_session=50,
                status_csv_row_count=25,
                jsonl_log_mb=60,
                session_age_hours=1.0,
            )
        )
        assert rec == Recommendation.SOFT
        assert reasons
        assert any("4" in r for r in reasons)
