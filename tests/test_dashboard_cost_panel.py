"""Tests for DASHBOARD-COST-PANEL — cost_panel() + /v2/cost-panel."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.dashboard.v2_routes import cost_panel, make_router


def test_cost_panel_empty_returns_zero_total(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("harness.budget.summary") as mock_sum:
        mock_sum.return_value = {}
        result = cost_panel()
    assert result["total_usd"] == 0.0
    assert result["by_engine"] == []
    assert result["cap_usd"] is None


def test_cost_panel_with_cap_and_engines(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    # Write a cap file at the default path
    from harness.budget import DEFAULT_CAP_PATH
    cap_path = Path(DEFAULT_CAP_PATH)
    cap_path.parent.mkdir(parents=True, exist_ok=True)
    cap_path.write_text(json.dumps({"monthly_cap_usd": 10.0}), encoding="utf-8")
    with patch("harness.budget.summary") as mock_sum:
        mock_sum.return_value = {
            "kimi": {"dispatches": 12.0, "total_cost_usd": 1.80},
            "deepseek": {"dispatches": 3.0, "total_cost_usd": 0.70},
        }
        result = cost_panel()
    assert result["total_usd"] == 2.50
    assert result["cap_usd"] == 10.0
    assert result["cap_pct"] == 25.0
    assert len(result["by_engine"]) == 2
    engines = {e["engine"]: e for e in result["by_engine"]}
    assert engines["kimi"]["usd"] == 1.80
    assert engines["kimi"]["calls"] == 12
    assert engines["deepseek"]["usd"] == 0.70
    assert engines["deepseek"]["calls"] == 3


def test_cost_panel_swallows_summary_error(monkeypatch) -> None:
    """If budget.summary raises, cost_panel still returns a safe default dict."""
    with patch("harness.budget.summary", side_effect=RuntimeError("db locked")):
        result = cost_panel()
    assert result["total_usd"] == 0.0


def test_cost_panel_route_http() -> None:
    app = FastAPI()
    app.include_router(make_router())
    with patch("harness.budget.summary") as mock_sum:
        mock_sum.return_value = {}
        client = TestClient(app)
        r = client.get("/v2/cost-panel")
    assert r.status_code == 200
    body = r.json()
    assert "total_usd" in body
    assert "by_engine" in body


def test_snapshot_embeds_cost_panel(monkeypatch, tmp_path: Path) -> None:
    """_snapshot() includes v2.cost so the WS stream carries cost telemetry."""
    monkeypatch.chdir(tmp_path)
    with patch("harness.budget.summary") as mock_sum:
        mock_sum.return_value = {
            "kimi": {"dispatches": 1.0, "total_cost_usd": 0.5},
        }
        from harness.dashboard.app import _snapshot
        snap = _snapshot()
    assert "cost" in snap["v2"]
    assert snap["v2"]["cost"]["total_usd"] == 0.5
