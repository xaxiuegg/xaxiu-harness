"""Tests for harness.state.inspect (STATE-INSPECT row #18 companion)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.errors import ConfigCorruption
from harness.state.inspect import (
    render_state_json,
    summarize_active_dispatches,
    summarize_engine_slots,
    summarize_phase_statuses,
    summarize_wave_plan,
)


def _state(tmp_path: Path, **overrides) -> Path:
    base = {
        "schema_version": 1,
        "loop_status": "armed",
        "tick_count": 11,
        "last_tick_at": "2026-05-21T01:00:00Z",
        "phase_status": {
            "creativity": "armed",
            "developing": "armed",
            "testing": "armed",
        },
        "active_dispatches": [
            {"task_id": "abc", "engine": "swarm/kimi", "wave_id": "W-1",
             "dispatched_at": "2026-05-21T01:00:00Z"},
        ],
        "wave_plan": [
            {"id": "wave-A", "status": "done"},
            {"id": "wave-B", "status": "done"},
            {"id": "wave-C", "status": "in_progress"},
            {"id": "wave-D", "status": "planned"},
        ],
        "escalations": [],
        "engine_slots": {
            "kimi": {"max_parallel": 6, "in_flight": ["abc"]},
            "kimi-api": {"max_parallel": 6, "in_flight": []},
            "deepseek": {"max_parallel": 1, "in_flight": []},
        },
    }
    base.update(overrides)
    p = tmp_path / "state.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


class TestSummaries:
    def test_wave_plan_counts(self) -> None:
        out = summarize_wave_plan([
            {"id": "a", "status": "done"},
            {"id": "b", "status": "done"},
            {"id": "c", "status": "planned"},
        ])
        assert "2 done" in out
        assert "1 planned" in out

    def test_wave_plan_empty(self) -> None:
        assert summarize_wave_plan([]) == "(none)"

    def test_active_dispatches_render(self) -> None:
        out = summarize_active_dispatches([
            {"task_id": "abc", "engine": "swarm/kimi", "wave_id": "W-1"}
        ])
        assert "abc" in out
        assert "swarm/kimi" in out

    def test_active_dispatches_empty(self) -> None:
        assert summarize_active_dispatches([]) == "(none)"

    def test_phase_all_armed(self) -> None:
        out = summarize_phase_statuses({"a": "armed", "b": "armed"})
        assert "all 2 armed" in out

    def test_phase_mixed(self) -> None:
        out = summarize_phase_statuses({"a": "armed", "b": "paused"})
        assert "1 armed" in out
        assert "paused" in out

    def test_engine_slots(self) -> None:
        out = summarize_engine_slots({
            "kimi": {"max_parallel": 6, "in_flight": ["a", "b"]},
            "deepseek": {"max_parallel": 1, "in_flight": []},
        })
        assert "kimi 2/6" in out
        assert "deepseek 0/1" in out


class TestRender:
    def test_pretty_contains_sections(self, tmp_path: Path) -> None:
        p = _state(tmp_path)
        out = render_state_json(p, fmt="pretty")
        for header in ("Loop:", "Phases:", "Active dispatches", "Wave plan", "Escalations", "Engine slots:"):
            assert header in out, f"missing {header!r} in pretty output"

    def test_json_roundtrip(self, tmp_path: Path) -> None:
        p = _state(tmp_path)
        out = render_state_json(p, fmt="json")
        data = json.loads(out)
        assert data["tick_count"] == 11

    def test_compact_one_line(self, tmp_path: Path) -> None:
        p = _state(tmp_path)
        out = render_state_json(p, fmt="compact")
        assert "\n" not in out
        assert "loop=armed" in out
        assert "tick=11" in out

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            render_state_json(tmp_path / "missing.json")

    def test_corrupt_json_raises_configcorruption(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        with pytest.raises(ConfigCorruption):
            render_state_json(p)


