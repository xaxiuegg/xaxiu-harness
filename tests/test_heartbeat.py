"""Tests for harness.heartbeat (HEARTBEAT row #17)."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from harness import heartbeat as hb
from harness.heartbeat import Heartbeat, pulse, read_heartbeat, format_for_human


def _state_fixture(tmp_path: Path, **overrides) -> Path:
    base = {
        "schema_version": 1,
        "loop_status": "armed",
        "tick_count": 7,
        "last_tick_at": "2026-05-21T01:00:00Z",
        "phase_status": {
            "creativity": "armed",
            "developing": "armed",
        },
        "active_dispatches": [{"task_id": "x"}],
        "engine_slots": {
            "kimi": {"max_parallel": 6, "in_flight": ["x", "y"]},
            "kimi-api": {"max_parallel": 6, "in_flight": []},
            "deepseek": {"max_parallel": 1, "in_flight": []},
        },
        "escalations": [],
    }
    base.update(overrides)
    p = tmp_path / "state.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


class TestHeartbeatSchema:
    def test_minimal_valid(self) -> None:
        h = Heartbeat(
            pulsed_at="2026-05-21T01:00:00Z",
            tick_count=1,
            loop_status="armed",
            active_dispatches=0,
            in_flight_kimi=0,
            in_flight_deepseek=0,
        )
        assert h.tick_count == 1

    def test_bad_iso_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Heartbeat(
                pulsed_at="not-an-iso",
                tick_count=1,
                loop_status="armed",
                active_dispatches=0,
                in_flight_kimi=0,
                in_flight_deepseek=0,
            )

    def test_negative_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Heartbeat(
                pulsed_at="2026-05-21T01:00:00Z",
                tick_count=-1,
                loop_status="armed",
                active_dispatches=0,
                in_flight_kimi=0,
                in_flight_deepseek=0,
            )


class TestPulse:
    def test_pulse_derives_from_state(self, tmp_path: Path) -> None:
        state = _state_fixture(tmp_path)
        out = tmp_path / "heartbeat.json"
        beat = pulse(state_path=state, heartbeat_path=out)
        assert beat.tick_count == 7
        assert beat.loop_status == "armed"
        assert beat.active_dispatches == 1
        assert beat.in_flight_kimi == 2
        assert beat.in_flight_deepseek == 0
        assert beat.phase_statuses == {"creativity": "armed", "developing": "armed"}
        assert out.exists()

    def test_pulse_missing_state_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            pulse(state_path=tmp_path / "missing.json", heartbeat_path=tmp_path / "h.json")

    def test_roundtrip(self, tmp_path: Path) -> None:
        state = _state_fixture(tmp_path)
        out = tmp_path / "heartbeat.json"
        beat = pulse(state_path=state, heartbeat_path=out)
        rt = read_heartbeat(out)
        assert rt is not None
        assert rt == beat

    def test_atomic_write_failure_preserves_original(self, tmp_path: Path) -> None:
        state = _state_fixture(tmp_path)
        out = tmp_path / "heartbeat.json"
        # Write a known-good heartbeat first
        pulse(state_path=state, heartbeat_path=out)
        original = out.read_text()
        # Now mock os.replace to fail; original survives
        with patch("harness.heartbeat.os.replace", side_effect=OSError):
            with pytest.raises(OSError):
                pulse(state_path=state, heartbeat_path=out)
        assert out.read_text() == original

    def test_last_escalation_id_picked_up(self, tmp_path: Path) -> None:
        state = _state_fixture(
            tmp_path,
            escalations=[{"id": "esc-001", "tag": "L5.x"}, {"id": "esc-002"}],
        )
        beat = pulse(state_path=state, heartbeat_path=tmp_path / "h.json")
        assert beat.last_escalation_id == "esc-002"


class TestFormat:
    def test_none_returns_never(self) -> None:
        assert "never" in format_for_human(None).lower()

    def test_fresh_beat_renders_summary(self) -> None:
        now = datetime.now(timezone.utc)
        beat = Heartbeat(
            pulsed_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            tick_count=11,
            loop_status="armed",
            active_dispatches=2,
            in_flight_kimi=2,
            in_flight_deepseek=0,
            phase_statuses={"creativity": "armed"},
        )
        s = format_for_human(beat, now=now + timedelta(seconds=5))
        assert "tick #11" in s
        assert "2 active" in s
        assert "STALE" not in s

    def test_stale_beat_marked(self) -> None:
        now = datetime.now(timezone.utc)
        beat = Heartbeat(
            pulsed_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            tick_count=11,
            loop_status="armed",
            active_dispatches=0,
            in_flight_kimi=0,
            in_flight_deepseek=0,
        )
        s = format_for_human(beat, now=now + timedelta(seconds=600), stale_after_seconds=300)
        assert "STALE" in s


class TestCLI:
    def test_heartbeat_help(self) -> None:
        from harness.cli import cli
        result = CliRunner().invoke(cli, ["heartbeat", "--help"])
        assert result.exit_code == 0
        assert "pulse" in result.output
        assert "show" in result.output

    def test_heartbeat_show_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        # Need coord/dev_loop/ to exist so the default path resolves to something
        (tmp_path / "coord" / "dev_loop").mkdir(parents=True)
        from harness.cli import cli
        result = CliRunner().invoke(cli, ["heartbeat", "show"])
        assert result.exit_code == 0
        assert "never" in result.output.lower()

    def test_heartbeat_pulse_smoke(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        coord = tmp_path / "coord" / "dev_loop"
        coord.mkdir(parents=True)
        (coord / "state.json").write_text(
            json.dumps({
                "schema_version": 1,
                "loop_status": "armed",
                "tick_count": 1,
                "phase_status": {},
                "active_dispatches": [],
                "engine_slots": {},
            }),
            encoding="utf-8",
        )
        from harness.cli import cli
        result = CliRunner().invoke(cli, ["heartbeat", "pulse"])
        assert result.exit_code == 0, result.output
        assert (coord / "heartbeat.json").exists()
