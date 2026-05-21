"""Tests for harness.dashboard (Wave 3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from harness.dashboard.app import create_app
from harness.heartbeat import pulse as _pulse


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Provide a TestClient with working-directory isolation."""
    monkeypatch.chdir(tmp_path)
    # Ensure coord dirs exist
    (tmp_path / "coord" / "dev_loop").mkdir(parents=True)
    (tmp_path / "coord" / "observer").mkdir(parents=True)
    return TestClient(create_app())


@pytest.fixture
def state_json(tmp_path: Path) -> Path:
    """Write a minimal state.json and return its path."""
    p = tmp_path / "coord" / "dev_loop" / "state.json"
    p.write_text(
        json.dumps({
            "schema_version": 1,
            "loop_status": "armed",
            "tick_count": 3,
            "last_tick_at": "2026-05-21T01:00:00Z",
            "phase_status": {"creativity": "armed", "developing": "armed"},
            "active_dispatches": [
                {"task_id": "t1", "engine": "kimi", "wave_id": "W3"},
            ],
            "wave_plan": [
                {"id": "W3", "status": "in_progress"},
                {"id": "W4", "status": "planned"},
            ],
            "engine_slots": {
                "kimi": {"max_parallel": 6, "in_flight": ["t1"]},
                "deepseek": {"max_parallel": 1, "in_flight": []},
            },
            "escalations": [],
        }),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def status_csv(tmp_path: Path) -> Path:
    """Write a minimal STATUS.csv and return its path."""
    p = tmp_path / "coord" / "STATUS.csv"
    p.write_text(
        "ID,Category,Title,Status,Owner,Effort,Updated,Notes\n"
        "T1,cat,Task One,shipped,Claude,-,2026-05-21,\n"
        "T2,cat,Task Two,in_progress,Kimi,-,2026-05-21,\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# 1. App factory + route registry
# ---------------------------------------------------------------------------


class TestAppFactory:
    def test_routes_exist(self) -> None:
        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/" in routes
        assert "/api/state" in routes
        assert "/api/status" in routes
        assert "/api/heartbeat" in routes
        assert "/api/flags" in routes
        assert "/api/summary" in routes
        assert "/ws" in routes


# ---------------------------------------------------------------------------
# 2. /api/state
# ---------------------------------------------------------------------------


class TestApiState:
    def test_empty_when_no_state(self, client: TestClient) -> None:
        response = client.get("/api/state")
        assert response.status_code == 200
        assert response.json() == {}

    def test_returns_state_json(self, client: TestClient, state_json: Path) -> None:
        response = client.get("/api/state")
        assert response.status_code == 200
        data = response.json()
        assert data.get("loop_status") == "armed"
        assert data.get("tick_count") == 3


# ---------------------------------------------------------------------------
# 3. /api/status
# ---------------------------------------------------------------------------


class TestApiStatus:
    def test_empty_when_no_csv(self, client: TestClient) -> None:
        response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_rows(self, client: TestClient, status_csv: Path) -> None:
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "T1"
        assert data[1]["status"] == "in_progress"


# ---------------------------------------------------------------------------
# 4. /api/heartbeat
# ---------------------------------------------------------------------------


class TestApiHeartbeat:
    def test_null_when_missing(self, client: TestClient) -> None:
        response = client.get("/api/heartbeat")
        assert response.status_code == 200
        assert response.json() is None

    def test_valid_after_pulse(self, client: TestClient, state_json: Path, tmp_path: Path) -> None:
        hb_path = tmp_path / "coord" / "dev_loop" / "heartbeat.json"
        beat = _pulse(state_path=state_json, heartbeat_path=hb_path)
        response = client.get("/api/heartbeat")
        assert response.status_code == 200
        data = response.json()
        assert data is not None
        assert data["tick_count"] == beat.tick_count
        assert data["loop_status"] == beat.loop_status


# ---------------------------------------------------------------------------
# 5. /api/flags
# ---------------------------------------------------------------------------


class TestApiFlags:
    def test_empty_when_no_flags(self, client: TestClient) -> None:
        response = client.get("/api/flags")
        assert response.status_code == 200
        assert response.json() == []

    @patch("harness.dashboard.app.list_pending_flags")
    def test_populated(self, mock_list, client: TestClient) -> None:
        from harness.observer.flags import Flag, FlagSeverity

        mock_list.return_value = {
            FlagSeverity.HIGH: [
                Flag(
                    id="FLAG-2026-05-21-1",
                    severity=FlagSeverity.HIGH,
                    category="test",
                    summary="test flag",
                    detail="detail",
                    evidence=["ev1"],
                    raised_at="2026-05-21T01:00:00Z",
                    cycle_id="c1",
                ),
            ],
            FlagSeverity.CRITICAL: [],
        }
        response = client.get("/api/flags")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "FLAG-2026-05-21-1"


# ---------------------------------------------------------------------------
# 6. /api/summary
# ---------------------------------------------------------------------------


class TestApiSummary:
    def test_aggregates(self, client: TestClient, state_json: Path, status_csv: Path) -> None:
        response = client.get("/api/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["status_counts"] == {"shipped": 1, "in_progress": 1}
        assert data["wave_plan_counts"] == {"in_progress": 1, "planned": 1}
        assert data["active_dispatch_count"] == 1


# ---------------------------------------------------------------------------
# 7. WebSocket /ws
# ---------------------------------------------------------------------------


class TestWebSocket:
    def test_sends_snapshot(self, client: TestClient, state_json: Path, status_csv: Path) -> None:
        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            assert data["type"] == "snapshot"
            assert "ts" in data
            assert "state" in data
            assert "status_summary" in data
            assert "heartbeat" in data
            assert "flags" in data
            assert "active_dispatches" in data
            assert data["state"].get("loop_status") == "armed"


# ---------------------------------------------------------------------------
# 8. Frontend smoke
# ---------------------------------------------------------------------------


class TestFrontend:
    def test_index_html_serves(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        text = response.text
        assert "xaxiu-harness" in text
        assert "/static/script.js" in text
        assert "/static/style.css" in text

    def test_static_files_exist(self) -> None:
        static_dir = Path(__file__).resolve().parents[1] / "src" / "harness" / "dashboard" / "static"
        assert (static_dir / "index.html").exists()
        assert (static_dir / "style.css").exists()
        assert (static_dir / "script.js").exists()


# ---------------------------------------------------------------------------
# 9. CLI wiring smoke
# ---------------------------------------------------------------------------


class TestCLI:
    @patch("harness.dashboard.server.serve")
    def test_dashboard_serve_invokes_serve(self, mock_serve: MagicMock) -> None:
        from harness.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["dashboard-serve", "--port", "7879"])
        assert result.exit_code == 0, result.output
        mock_serve.assert_called_once_with(host="127.0.0.1", port=7879)

    def test_dashboard_serve_help(self) -> None:
        from harness.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["dashboard-serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output
