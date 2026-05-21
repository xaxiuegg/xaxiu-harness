"""Tests for harness.replay — decision archaeology."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from harness.replay import (
    ReplayEvent,
    ReplayReport,
    format_for_human,
    replay_dispatch,
)


def _mock_conn(dispatch_row=None, fallback_rows=()):
    """Build a MagicMock sqlite connection returning the given rows."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor

    cursor.description = (
        ("id",), ("project",), ("packet_path",), ("backend",), ("model",),
        ("status",), ("outcome",), ("latency_ms",), ("fallback_to",),
        ("created_at",),
    )
    # fetchone is called first for dispatches, then fetchall for fallbacks.
    if dispatch_row is None:
        cursor.fetchone.return_value = None
    else:
        cursor.fetchone.return_value = tuple(
            dispatch_row.get(k) for k in (
                "id", "project", "packet_path", "backend", "model",
                "status", "outcome", "latency_ms", "fallback_to", "created_at",
            )
        )

    # For fallbacks query, description shape differs — we set per-call.
    def execute(query, *args, **kwargs):
        if "FROM fallbacks" in query:
            cursor.description = (
                ("from_backend",), ("to_backend",), ("reason",), ("timestamp",),
            )
            cursor.fetchall.return_value = [
                tuple(r.get(k) for k in ("from_backend", "to_backend", "reason", "timestamp"))
                for r in fallback_rows
            ]
        else:
            cursor.description = (
                ("id",), ("project",), ("packet_path",), ("backend",), ("model",),
                ("status",), ("outcome",), ("latency_ms",), ("fallback_to",),
                ("created_at",),
            )
        return cursor

    cursor.execute.side_effect = execute
    return conn


class TestReplayDispatch:
    def test_unknown_task_id_returns_empty_report(self) -> None:
        with patch("harness.replay.state_db.get_connection",
                   return_value=_mock_conn(dispatch_row=None)):
            report = replay_dispatch("nonexistent-id")
        assert report.events == []
        assert "no events" in report.summary.lower()
        assert report.final_outcome is None

    def test_simple_dispatch_renders_start_and_end(self) -> None:
        with patch("harness.replay.state_db.get_connection",
                   return_value=_mock_conn(
                       dispatch_row={
                           "id": "d-1", "project": "myproj", "packet_path": "p.md",
                           "backend": "kimi", "model": None, "status": "success",
                           "outcome": "success", "latency_ms": 12000,
                           "fallback_to": None, "created_at": "2026-05-21T01:00:00Z",
                       },
                       fallback_rows=(),
                   )), \
             patch("harness.replay._read_jsonl_entries", return_value=[]):
            report = replay_dispatch("d-1")
        kinds = [e.kind for e in report.events]
        assert "dispatch_start" in kinds
        assert "dispatch_end" in kinds
        assert "kimi" in report.summary

    def test_multi_engine_chain_in_summary(self) -> None:
        with patch("harness.replay.state_db.get_connection",
                   return_value=_mock_conn(
                       dispatch_row={
                           "id": "d-2", "project": "myproj", "packet_path": "p.md",
                           "backend": "kimi", "model": None, "status": "success",
                           "outcome": "success", "latency_ms": 25000,
                           "fallback_to": "deepseek", "created_at": "2026-05-21T01:00:00Z",
                       },
                       fallback_rows=({
                           "from_backend": "kimi", "to_backend": "deepseek",
                           "reason": "timeout", "timestamp": "2026-05-21T01:10:00Z",
                       },),
                   )), \
             patch("harness.replay._read_jsonl_entries", return_value=[]):
            report = replay_dispatch("d-2")
        assert "kimi -> deepseek -> success" in report.summary
        fallback_events = [e for e in report.events if e.kind == "fallback"]
        assert len(fallback_events) == 1
        assert fallback_events[0].engine == "deepseek"

    def test_jsonl_supplement_appears(self) -> None:
        with patch("harness.replay.state_db.get_connection",
                   return_value=_mock_conn(
                       dispatch_row={
                           "id": "d-3", "project": "myproj", "packet_path": "p.md",
                           "backend": "kimi", "model": None, "status": "success",
                           "outcome": "success", "latency_ms": 5000,
                           "fallback_to": None, "created_at": "2026-05-21T01:00:00Z",
                       },
                       fallback_rows=(),
                   )), \
             patch("harness.replay._read_jsonl_entries", return_value=[
                 {"timestamp": "2026-05-21T01:05:00Z", "project": "myproj",
                  "backend": "kimi", "outcome": "success", "latency_ms": 4800,
                  "fallback_to": None, "packet_path": "p.md", "model": None},
             ]):
            report = replay_dispatch("d-3")
        jsonl_events = [e for e in report.events if e.kind == "engine_call"]
        assert len(jsonl_events) == 1
        assert jsonl_events[0].latency_ms == 4800

    def test_events_sorted_by_timestamp(self) -> None:
        with patch("harness.replay.state_db.get_connection",
                   return_value=_mock_conn(
                       dispatch_row={
                           "id": "d-4", "project": "myproj", "packet_path": "p.md",
                           "backend": "kimi", "model": None, "status": "success",
                           "outcome": "success", "latency_ms": 3000,
                           "fallback_to": None, "created_at": "2026-05-21T02:00:00Z",
                       },
                       fallback_rows=(),
                   )), \
             patch("harness.replay._read_jsonl_entries", return_value=[
                 {"timestamp": "2026-05-21T01:00:00Z", "project": "myproj",
                  "backend": "kimi", "outcome": "success", "latency_ms": 1000,
                  "fallback_to": None, "packet_path": "p.md", "model": None},
             ]):
            report = replay_dispatch("d-4")
        timestamps = [e.timestamp for e in report.events]
        assert timestamps == sorted(timestamps)


class TestFormatForHuman:
    def test_empty_report_renders_no_events(self) -> None:
        rpt = ReplayReport(task_id="x", summary="(no events)")
        s = format_for_human(rpt)
        assert "Replay: x" in s
        assert "no events" in s.lower()

    def test_populated_report_includes_events(self) -> None:
        rpt = ReplayReport(
            task_id="abc",
            events=[
                ReplayEvent(
                    timestamp="2026-05-21T01:00:00Z",
                    kind="dispatch_start",
                    engine="kimi",
                    detail="project=p packet=x",
                ),
                ReplayEvent(
                    timestamp="2026-05-21T01:05:00Z",
                    kind="dispatch_end",
                    engine="kimi",
                    detail="status=success",
                    latency_ms=300000,
                ),
            ],
            summary="kimi -> success",
            total_elapsed_ms=300000,
            final_outcome="success",
        )
        s = format_for_human(rpt)
        assert "Summary: kimi -> success" in s
        assert "300000 ms" in s
        assert "dispatch_start" in s
        assert "[300000ms]" in s


class TestReplayCLI:
    def test_replay_help(self) -> None:
        from harness.cli import cli
        result = CliRunner().invoke(cli, ["replay", "--help"])
        assert result.exit_code == 0
        assert "TASK_ID" in result.output

    def test_replay_unknown_id_exits_clean(self) -> None:
        from harness.cli import cli
        with patch("harness.replay.state_db.get_connection",
                   return_value=_mock_conn(dispatch_row=None)), \
             patch("harness.replay._read_jsonl_entries", return_value=[]):
            result = CliRunner().invoke(cli, ["replay", "ghost-id"])
        assert result.exit_code == 0
        assert "ghost-id" in result.output
        assert "no events" in result.output.lower()

    def test_replay_json_format(self) -> None:
        from harness.cli import cli
        with patch("harness.replay.state_db.get_connection",
                   return_value=_mock_conn(
                       dispatch_row={
                           "id": "z-1", "project": "p", "packet_path": "x",
                           "backend": "kimi", "model": None, "status": "success",
                           "outcome": "success", "latency_ms": 1000,
                           "fallback_to": None, "created_at": "2026-05-21T01:00:00Z",
                       },
                       fallback_rows=(),
                   )), \
             patch("harness.replay._read_jsonl_entries", return_value=[]):
            result = CliRunner().invoke(cli, ["replay", "z-1", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["task_id"] == "z-1"
        assert "events" in payload
