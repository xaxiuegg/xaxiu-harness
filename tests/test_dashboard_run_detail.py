"""Tests for dashboard /v2/runs/<id> HTML view."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.dashboard.v2_routes import make_router


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(make_router())
    return app


def test_run_detail_returns_html(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json", {
        "state": "running", "started_at": "2026-05-21T01:00:00Z",
    })
    _write(tmp_path / "runs" / "r1" / "plan.json", {"tasks": [{"worker_id": "w1"}]})
    client = TestClient(_make_app())
    r = client.get("/v2/runs/r1")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "run <code>r1</code>" in r.text
    assert "state: <strong" in r.text


def test_run_detail_includes_workers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json", {"state": "completed"})
    _write(tmp_path / "runs" / "r1" / "plan.json", {"tasks": []})
    _write(tmp_path / "runs" / "r1" / "checkpoints" / "worker-1.json", {
        "worker_id": "worker-1", "state": "completed",
        "tests_passed": True, "files_modified": ["a.txt", "b.txt"],
        "commit_sha": "abc1234",
    })
    client = TestClient(_make_app())
    r = client.get("/v2/runs/r1")
    assert r.status_code == 200
    assert "worker-1" in r.text
    assert "abc1234" in r.text
    assert "a.txt" in r.text


def test_run_detail_unknown_run_renders_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(_make_app())
    r = client.get("/v2/runs/does-not-exist")
    assert r.status_code == 200
    assert "no workers" in r.text
    assert 'state: <strong class="state-unknown">unknown' in r.text
