"""Tests for harness.session.signals."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.session.signals import (
    DEFAULT_LOG_PATH,
    DEFAULT_STATE_PATH,
    DEFAULT_STATUS_PATH,
    Signals,
    _cpu_pct,
    _disk_pct_free,
    _git_commits_since,
    _jsonl_log_mb,
    _load_state,
    _process_rss_mb,
    _session_age_hours,
    _system_memory_pct,
    collect_signals,
)


class TestLoadState:
    def test_missing_file(self, tmp_path: Path) -> None:
        assert _load_state(tmp_path / "nope.json") == {}

    def test_bad_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert _load_state(p) == {}

    def test_valid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "good.json"
        p.write_text('{"tick_count": 7}')
        assert _load_state(p) == {"tick_count": 7}


class TestSessionAgeHours:
    def test_missing_created_at(self) -> None:
        assert _session_age_hours({}) == 0.0

    def test_valid_iso(self) -> None:
        now = datetime.now(timezone.utc)
        assert _session_age_hours({"created_at": now.isoformat()}) == pytest.approx(0.0, abs=0.01)

    def test_z_suffix(self) -> None:
        now = datetime.now(timezone.utc)
        assert _session_age_hours({"created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}) == pytest.approx(0.0, abs=0.01)


class TestGitCommitsSince:
    def test_success(self) -> None:
        with patch("harness.session.signals.subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout="42\n")
            assert _git_commits_since("2024-01-01T00:00:00Z") == 42
            args = m.call_args[0][0]
            assert "--since=2024-01-01T00:00:00Z" in args

    def test_failure(self) -> None:
        with patch("harness.session.signals.subprocess.run") as m:
            m.return_value = MagicMock(returncode=1, stdout="")
            assert _git_commits_since("x") == 0


class TestPsutilHelpers:
    def test_system_memory_no_psutil(self) -> None:
        with patch("harness.session.signals.psutil", None):
            assert _system_memory_pct() == 0.0

    def test_system_memory_ok(self) -> None:
        mock = MagicMock()
        mock.virtual_memory.return_value.percent = 72.5
        with patch("harness.session.signals.psutil", mock):
            assert _system_memory_pct() == 72.5

    def test_cpu_no_psutil(self) -> None:
        with patch("harness.session.signals.psutil", None):
            assert _cpu_pct() == 0.0

    def test_cpu_ok(self) -> None:
        mock = MagicMock()
        mock.cpu_percent.return_value = 12.0
        with patch("harness.session.signals.psutil", mock):
            assert _cpu_pct() == 12.0

    def test_disk_no_psutil(self) -> None:
        with patch("harness.session.signals.psutil", None):
            assert _disk_pct_free() == 100.0

    def test_disk_ok(self) -> None:
        mock = MagicMock()
        mock.disk_usage.return_value = MagicMock(free=50 * 1024**3, total=100 * 1024**3)
        with patch("harness.session.signals.psutil", mock):
            assert _disk_pct_free() == 50.0

    def test_rss_no_psutil(self) -> None:
        with patch("harness.session.signals.psutil", None):
            assert _process_rss_mb() == 0

    def test_rss_ok(self) -> None:
        mock = MagicMock()
        proc = MagicMock()
        proc.memory_info.return_value.rss = 2048 * 1024 * 1024
        mock.Process.return_value = proc
        with patch("harness.session.signals.psutil", mock):
            assert _process_rss_mb() == 2048

    def test_rss_exception(self) -> None:
        mock = MagicMock()
        mock.Process.side_effect = Exception("nope")
        with patch("harness.session.signals.psutil", mock):
            assert _process_rss_mb() == 0


class TestJsonlLogMb:
    def test_missing(self, tmp_path: Path) -> None:
        assert _jsonl_log_mb(tmp_path / "log.jsonl") == 0.0

    def test_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_bytes(b"x" * (2 * 1024 * 1024))
        assert _jsonl_log_mb(p) == 2.0


class TestCollectSignals:
    def test_all_zero_when_missing(self, tmp_path: Path) -> None:
        with patch("harness.session.signals.psutil", None):
            s = collect_signals(
                state_path=tmp_path / "state.json",
                status_path=tmp_path / "STATUS.csv",
                log_path=tmp_path / "log.jsonl",
            )
        assert isinstance(s, Signals)
        assert s.tick_count == 0
        assert s.active_dispatch_count == 0
        assert s.mem_pct == 0.0

    def test_reads_state_and_status(self, tmp_path: Path) -> None:
        state = {"created_at": "2024-01-01T00:00:00Z", "tick_count": 3, "active_dispatches": [{"id": "a"}]}
        (tmp_path / "state.json").write_text(json.dumps(state))
        (tmp_path / "STATUS.csv").write_text(
            "id,category,title,status,owner,effort,updated,notes\n"
            "1,a,b,todo,me,1,2024-01-01,none\n"
        )
        with patch("harness.session.signals.psutil", None):
            s = collect_signals(
                state_path=tmp_path / "state.json",
                status_path=tmp_path / "STATUS.csv",
                log_path=tmp_path / "log.jsonl",
            )
        assert s.tick_count == 3
        assert s.active_dispatch_count == 1
        assert s.status_csv_row_count == 1
        assert s.session_age_hours > 0
