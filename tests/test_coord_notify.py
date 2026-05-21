"""Tests for harness.coord.notify."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness.coord.notify import notify, write_notify, post_webhook


def test_write_notify_creates_json_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    p = write_notify(run_dir, {"run_id": "r1", "success": True})
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data == {"run_id": "r1", "success": True}


def test_write_notify_atomic_replaces_existing(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    write_notify(run_dir, {"version": 1})
    write_notify(run_dir, {"version": 2})
    data = json.loads((run_dir / "notify.json").read_text())
    assert data["version"] == 2


def test_post_webhook_returns_false_on_empty_url() -> None:
    assert post_webhook("", {"x": 1}) is False


def test_post_webhook_swallows_url_error() -> None:
    with patch("harness.coord.notify.urllib.request.urlopen",
               side_effect=OSError("connection refused")):
        assert post_webhook("http://invalid", {"x": 1}) is False


def test_post_webhook_success() -> None:
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value.status = 200
    with patch("harness.coord.notify.urllib.request.urlopen", return_value=mock_resp):
        assert post_webhook("http://ok", {"x": 1}) is True


def test_notify_writes_file_and_returns_tuple(tmp_path: Path) -> None:
    p, posted = notify(tmp_path / "runs" / "r1", {"x": 1})
    assert p.exists()
    assert posted is False  # no webhook url


def test_integrator_writes_notify_on_success(tmp_path: Path, monkeypatch) -> None:
    """integrate() best-effort writes notify.json on the success path."""
    from harness.coord.integrator import integrate
    from harness.coord.run_state import write_run_state
    from harness.coord.schemas import IntegratorStatus, RunState, RunStateLiteral

    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    write_run_state(run_dir / "run_state.json", RunState(
        schema_version=1, run_id="r1", spec_path="s.md",
        state=RunStateLiteral.INTEGRATING, plan_path=str(run_dir / "plan.json"),
        started_at="2026-05-21T00:00:00Z", last_tick_at="2026-05-21T00:00:00Z",
        workers={}, integrator_status=IntegratorStatus(state="pending"),
        escalations=[],
    ))

    # Stub subprocess so pytest invocation doesn't actually run pytest
    with patch("harness.coord.integrator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="0 passed in 0.01s", returncode=0)
        integrate(run_dir)

    # notify.json should exist now
    notify_path = run_dir / "notify.json"
    assert notify_path.exists()
