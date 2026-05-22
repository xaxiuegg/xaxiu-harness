"""Path 3 / W5-B-observability: telemetry helper for `coord run --watch`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.coord.telemetry import (
    RunTelemetry, WorkerProgress, compute_telemetry, format_tick_line,
    read_cost_since, read_worker_progress,
)


# ---------------------------------------------------------------------------
# read_worker_progress
# ---------------------------------------------------------------------------

def _write_progress(run_dir: Path, worker_id: str, events: list[dict]) -> None:
    ckpt_dir = run_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    path = ckpt_dir / f"{worker_id}.progress.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


def test_worker_progress_no_events_yet(tmp_path: Path) -> None:
    plan_tasks = [{"worker_id": "w1", "steps": [{"step_id": "s1"}, {"step_id": "s2"}]}]
    progress = read_worker_progress(tmp_path, plan_tasks)
    assert len(progress) == 1
    assert progress[0].worker_id == "w1"
    assert progress[0].completed_steps == 0
    assert progress[0].total_steps == 2
    assert progress[0].last_event == "not_started"


def test_worker_progress_mid_run(tmp_path: Path) -> None:
    _write_progress(tmp_path, "w1", [
        {"event": "step_start", "step_id": "s1"},
        {"event": "step_done", "step_id": "s1"},
        {"event": "step_start", "step_id": "s2"},
    ])
    plan_tasks = [{"worker_id": "w1", "steps": [{"step_id": "s1"}, {"step_id": "s2"}]}]
    progress = read_worker_progress(tmp_path, plan_tasks)
    assert progress[0].completed_steps == 1
    assert progress[0].total_steps == 2
    assert progress[0].last_event == "step_start"
    assert progress[0].fraction == 0.5


def test_worker_progress_completed(tmp_path: Path) -> None:
    _write_progress(tmp_path, "w1", [
        {"event": "step_start", "step_id": "s1"},
        {"event": "step_done", "step_id": "s1"},
    ])
    plan_tasks = [{"worker_id": "w1", "steps": [{"step_id": "s1"}]}]
    progress = read_worker_progress(tmp_path, plan_tasks)
    assert progress[0].completed_steps == 1
    assert progress[0].fraction == 1.0


def test_worker_progress_skips_corrupt_jsonl_lines(tmp_path: Path) -> None:
    ckpt_dir = tmp_path / "checkpoints"
    ckpt_dir.mkdir()
    (ckpt_dir / "w1.progress.jsonl").write_text(
        '{"event": "step_done", "step_id": "s1"}\n'
        'not-json-garbage\n'
        '{"event": "step_done", "step_id": "s2"}\n',
        encoding="utf-8",
    )
    plan_tasks = [{"worker_id": "w1", "steps": [{}, {}, {}]}]
    progress = read_worker_progress(tmp_path, plan_tasks)
    # Two step_done events parsed, one garbage line skipped
    assert progress[0].completed_steps == 2


# ---------------------------------------------------------------------------
# read_cost_since
# ---------------------------------------------------------------------------

def test_read_cost_since_sums_entries(tmp_path: Path) -> None:
    ledger = tmp_path / "budget_ledger.jsonl"
    ledger.write_text(
        json.dumps({"timestamp": "2026-05-22T10:00:00+00:00",
                    "input_tokens": 10, "output_tokens": 20, "cost_usd": 0.001}) + "\n"
        + json.dumps({"timestamp": "2026-05-22T12:00:00+00:00",
                      "input_tokens": 30, "output_tokens": 40, "cost_usd": 0.003}) + "\n",
        encoding="utf-8",
    )
    cost, tin, tout = read_cost_since(ledger, "2026-05-22T09:00:00+00:00")
    assert cost == pytest.approx(0.004)
    assert tin == 40
    assert tout == 60


def test_read_cost_since_filters_old_entries(tmp_path: Path) -> None:
    ledger = tmp_path / "budget_ledger.jsonl"
    ledger.write_text(
        json.dumps({"timestamp": "2026-05-22T08:00:00+00:00",
                    "input_tokens": 100, "output_tokens": 200, "cost_usd": 0.01}) + "\n"
        + json.dumps({"timestamp": "2026-05-22T12:00:00+00:00",
                      "input_tokens": 10, "output_tokens": 20, "cost_usd": 0.001}) + "\n",
        encoding="utf-8",
    )
    cost, tin, tout = read_cost_since(ledger, "2026-05-22T11:00:00+00:00")
    assert cost == pytest.approx(0.001)
    assert tin == 10
    assert tout == 20


def test_read_cost_since_missing_ledger(tmp_path: Path) -> None:
    cost, tin, tout = read_cost_since(tmp_path / "absent.jsonl", "2026-01-01")
    assert (cost, tin, tout) == (0.0, 0, 0)


# ---------------------------------------------------------------------------
# compute_telemetry — ETA calculation
# ---------------------------------------------------------------------------

def test_compute_telemetry_eta_extrapolates(tmp_path: Path) -> None:
    """If 1 of 4 total steps done in 10 seconds, eta should be ~30 seconds."""
    _write_progress(tmp_path, "w1", [
        {"event": "step_start", "step_id": "s1"},
        {"event": "step_done", "step_id": "s1"},
    ])
    plan_tasks = [{"worker_id": "w1", "steps": [{}, {}, {}, {}]}]
    tel = compute_telemetry(
        tmp_path, plan_tasks,
        started_at_iso="2026-05-22T10:00:00+00:00",
        elapsed_seconds=10,
        ledger_path=tmp_path / "absent.jsonl",
    )
    assert tel.eta_seconds == 30
    assert tel.workers[0].completed_steps == 1


def test_compute_telemetry_eta_none_at_cold_start(tmp_path: Path) -> None:
    """Before any step completes, ETA should be None (no extrapolation)."""
    plan_tasks = [{"worker_id": "w1", "steps": [{}, {}]}]
    tel = compute_telemetry(
        tmp_path, plan_tasks,
        started_at_iso="2026-05-22T10:00:00+00:00",
        elapsed_seconds=3,
        ledger_path=tmp_path / "absent.jsonl",
    )
    assert tel.eta_seconds is None


# ---------------------------------------------------------------------------
# format_tick_line
# ---------------------------------------------------------------------------

def test_format_tick_line_minimal() -> None:
    tel = RunTelemetry(workers=[], total_cost_usd=0.0,
                       total_tokens_in=0, total_tokens_out=0,
                       elapsed_seconds=5, eta_seconds=None)
    out = format_tick_line(tel)
    assert out == "[5s]"


def test_format_tick_line_with_workers_and_cost() -> None:
    tel = RunTelemetry(
        workers=[
            WorkerProgress(worker_id="w1", completed_steps=2,
                           total_steps=3, last_event="step_done"),
            WorkerProgress(worker_id="w2", completed_steps=0,
                           total_steps=2, last_event="not_started"),
        ],
        total_cost_usd=0.0125, total_tokens_in=100, total_tokens_out=200,
        elapsed_seconds=12, eta_seconds=24,
    )
    out = format_tick_line(tel)
    assert "[12s]" in out
    assert "w1(2/3" in out
    assert "w2(0/2" in out
    assert "$0.0125" in out
    assert "tok=100/200" in out
    assert "eta=~24s" in out


def test_format_tick_line_eta_units() -> None:
    base = dict(workers=[], total_cost_usd=0.0,
                total_tokens_in=0, total_tokens_out=0,
                elapsed_seconds=0)
    assert "eta=~5s" in format_tick_line(RunTelemetry(**base, eta_seconds=5))
    assert "eta=~2m30s" in format_tick_line(RunTelemetry(**base, eta_seconds=150))
    assert "eta=~1h30m" in format_tick_line(RunTelemetry(**base, eta_seconds=5400))
