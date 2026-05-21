"""Tests for harness.session.monitor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.session.monitor import (
    CRISIS_TASK_NAME,
    HANDOFF_CRITICAL,
    HANDOFF_RECOMMENDED,
    CheckReport,
    ack_handoff,
    arm_crisis_check,
    check,
    crisis_check,
    _write_handoff_file,
)
from harness.session.recommender import Recommendation
from harness.session.signals import Signals


@pytest.fixture(autouse=True)
def _cleanup_handoff_files():
    yield
    for p in (HANDOFF_CRITICAL, HANDOFF_RECOMMENDED):
        if p.exists():
            p.unlink()


class TestWriteHandoffFile:
    def test_creates_file(self, tmp_path: Path) -> None:
        p = tmp_path / "handoff.md"
        sig = Signals(
            session_age_hours=1.0,
            tick_count=0,
            active_dispatch_count=0,
            commits_since_session=0,
            status_csv_row_count=0,
            mem_pct=0.0,
            claude_rss_mb=0,
            cpu_pct=0.0,
            disk_pct_free=100.0,
            jsonl_log_mb=0.0,
        )
        _write_handoff_file(p, Recommendation.SOFT, ["age"], sig)
        assert p.exists()
        text = p.read_text()
        assert "age" in text
        assert "soft" in text.lower()
        assert "```json" in text


class TestCheck:
    def test_none_does_not_write(self, tmp_path: Path) -> None:
        with patch("harness.session.monitor.collect_signals") as m_sig:
            m_sig.return_value = Signals(
                session_age_hours=1.0,
                tick_count=0,
                active_dispatch_count=0,
                commits_since_session=0,
                status_csv_row_count=0,
                mem_pct=0.0,
                claude_rss_mb=0,
                cpu_pct=0.0,
                disk_pct_free=100.0,
                jsonl_log_mb=0.0,
            )
            report = check()
        assert report.recommendation == Recommendation.NONE
        assert report.handoff_file_written is False
        assert not HANDOFF_CRITICAL.exists()
        assert not HANDOFF_RECOMMENDED.exists()

    def test_soft_writes_recommended(self) -> None:
        with patch("harness.session.monitor.collect_signals") as m_sig:
            m_sig.return_value = Signals(
                session_age_hours=5.0,
                tick_count=0,
                active_dispatch_count=0,
                commits_since_session=0,
                status_csv_row_count=0,
                mem_pct=0.0,
                claude_rss_mb=0,
                cpu_pct=0.0,
                disk_pct_free=100.0,
                jsonl_log_mb=0.0,
            )
            report = check()
        assert report.recommendation == Recommendation.SOFT
        assert report.handoff_file_written is True
        assert HANDOFF_RECOMMENDED.exists()
        assert not HANDOFF_CRITICAL.exists()

    def test_critical_writes_critical(self) -> None:
        with patch("harness.session.monitor.collect_signals") as m_sig:
            m_sig.return_value = Signals(
                session_age_hours=1.0,
                tick_count=0,
                active_dispatch_count=0,
                commits_since_session=0,
                status_csv_row_count=0,
                mem_pct=95.0,
                claude_rss_mb=0,
                cpu_pct=0.0,
                disk_pct_free=100.0,
                jsonl_log_mb=0.0,
            )
            report = check()
        assert report.recommendation == Recommendation.CRITICAL
        assert report.handoff_file_written is True
        assert HANDOFF_CRITICAL.exists()


class TestAckHandoff:
    def test_nothing_to_ack(self) -> None:
        ok, msg = ack_handoff()
        assert ok is False
        assert "No handoff" in msg

    def test_removes_files(self) -> None:
        HANDOFF_DIR = HANDOFF_RECOMMENDED.parent
        HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
        HANDOFF_RECOMMENDED.write_text("x")
        HANDOFF_CRITICAL.write_text("y")
        ok, msg = ack_handoff()
        assert ok is True
        assert "Removed" in msg
        assert not HANDOFF_RECOMMENDED.exists()
        assert not HANDOFF_CRITICAL.exists()


class TestCrisisCheck:
    def test_critical_toasts(self) -> None:
        with patch("harness.session.monitor.collect_signals") as m_sig:
            m_sig.return_value = Signals(
                session_age_hours=1.0,
                tick_count=0,
                active_dispatch_count=0,
                commits_since_session=0,
                status_csv_row_count=0,
                mem_pct=96.0,
                claude_rss_mb=0,
                cpu_pct=0.0,
                disk_pct_free=100.0,
                jsonl_log_mb=0.0,
            )
            with patch("harness.session.monitor.subprocess.run") as m_run:
                m_run.return_value = MagicMock(returncode=0)
                report = crisis_check()
        assert report.recommendation == Recommendation.CRITICAL
        m_run.assert_called_once()

    def test_none_no_toast(self) -> None:
        with patch("harness.session.monitor.collect_signals") as m_sig:
            m_sig.return_value = Signals(
                session_age_hours=1.0,
                tick_count=0,
                active_dispatch_count=0,
                commits_since_session=0,
                status_csv_row_count=0,
                mem_pct=0.0,
                claude_rss_mb=0,
                cpu_pct=0.0,
                disk_pct_free=100.0,
                jsonl_log_mb=0.0,
            )
            with patch("harness.session.monitor.subprocess.run") as m_run:
                report = crisis_check()
        assert report.recommendation == Recommendation.NONE
        m_run.assert_not_called()


class TestArmCrisisCheck:
    def test_no_powershell(self) -> None:
        with patch("harness.session.monitor._pwsh", return_value=None):
            ok, msg = arm_crisis_check()
        assert ok is False
        assert "PowerShell not found" in msg

    def test_registration_ok(self) -> None:
        with patch("harness.session.monitor._pwsh", return_value="powershell.exe"):
            with patch("harness.session.monitor.subprocess.run") as m_run:
                m_run.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
                ok, msg = arm_crisis_check()
        assert ok is True
        assert CRISIS_TASK_NAME in msg

    def test_registration_failure(self) -> None:
        with patch("harness.session.monitor._pwsh", return_value="powershell.exe"):
            with patch("harness.session.monitor.subprocess.run") as m_run:
                m_run.return_value = MagicMock(returncode=1, stdout="", stderr="bad")
                ok, msg = arm_crisis_check()
        assert ok is False
        assert "bad" in msg
