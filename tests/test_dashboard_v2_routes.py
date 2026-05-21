"""Tests for harness.dashboard.v2_routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness.dashboard.v2_routes import list_runs, list_workers, proxy_state, make_router


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_list_runs_returns_empty_when_no_runs_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert list_runs() == []


def test_list_runs_summarises_each_run(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json",
           {"state": "running", "started_at": "2026-05-21T01:00:00Z"})
    _write(tmp_path / "runs" / "r1" / "plan.json",
           {"tasks": [{"worker_id": "worker-1"}, {"worker_id": "worker-2"}]})
    runs = list_runs()
    assert runs == [{
        "run_id": "r1",
        "state": "running",
        "tasks": 2,
        "started_at": "2026-05-21T01:00:00Z",
        "last_tick_at": None,
    }]


def test_list_workers_empty_when_no_checkpoints(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert list_workers("does-not-exist") == []


def test_list_workers_includes_state_and_commit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "checkpoints" / "worker-1.json", {
        "worker_id": "worker-1",
        "state": "completed",
        "tests_passed": True,
        "files_modified": ["a.txt"],
        "commit_sha": "abc1234",
        "updated_at": "2026-05-21T01:00:00Z",
    })
    workers = list_workers("r1")
    assert workers == [{
        "worker_id": "worker-1",
        "state": "completed",
        "tests_passed": True,
        "files_modified": ["a.txt"],
        "commit_sha": "abc1234",
        "updated_at": "2026-05-21T01:00:00Z",
    }]


def test_proxy_state_returns_no_state_file_sentinel(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert proxy_state() == {"status": "no-state-file"}


def test_proxy_state_returns_real_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / ".harness" / "proxy_state.json", {"keys": ["k1", "k2"]})
    assert proxy_state() == {"keys": ["k1", "k2"]}


def test_router_endpoints_are_wired(monkeypatch, tmp_path):
    from fastapi import FastAPI
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "runs" / "r1" / "run_state.json", {"state": "running"})
    _write(tmp_path / "runs" / "r1" / "plan.json", {"tasks": []})
    _write(tmp_path / "runs" / "r1" / "checkpoints" / "worker-1.json",
           {"worker_id": "worker-1", "state": "completed"})

    app = FastAPI()
    app.include_router(make_router())
    client = TestClient(app)

    r = client.get("/v2/runs")
    assert r.status_code == 200
    assert r.json()[0]["run_id"] == "r1"

    r = client.get("/v2/runs/r1/workers")
    assert r.status_code == 200
    assert r.json()[0]["worker_id"] == "worker-1"

    r = client.get("/v2/proxy-state")
    assert r.status_code == 200
