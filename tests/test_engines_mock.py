"""Tests for src.harness.engines.mock."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from harness._constants import SUPPORTED_BACKENDS
from harness.adapters.schema import AdapterConfig, ObserverConfig, StatusTrackingConfig
from harness.engines.concrete import get_engine
from harness.engines.dispatcher import dispatch_packet
from harness.engines.mock import (
    MockEngine,
    MockResponseSet,
    _default_waveplan_stub,
    _default_worker_stub,
)


class TestMockEngineUnit:
    def test_waveplan_stub_contains_schema_version(self) -> None:
        engine = MockEngine()
        response = engine.dispatch("decompose this spec into a WavePlan", "", {})
        assert response.success is True
        assert '"schema_version": 1' in response.text
        assert "MOCK-RUN-ID-PLACEHOLDER" in response.text

    def test_worker_stub_contains_file_block(self) -> None:
        engine = MockEngine()
        response = engine.dispatch("implement step s1", "", {})
        assert response.success is True
        assert "FILE: mock-out-1.txt" in response.text
        assert ">>>>>>> REPLACE" in response.text
        assert "hello from MockEngine" in response.text

    def test_fixture_file_matching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixtures = {"special prompt": "special response"}
        fixture_file = tmp_path / "fixtures.json"
        fixture_file.write_text(json.dumps(fixtures), encoding="utf-8")
        monkeypatch.setenv("HARNESS_MOCK_FIXTURE_PATH", str(fixture_file))

        engine = MockEngine()
        response = engine.dispatch("this contains a special prompt for test", "", {})
        assert response.success is True
        assert response.text == "special response"

    def test_fixture_file_falls_back_on_no_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixtures = {"other prompt": "other response"}
        fixture_file = tmp_path / "fixtures.json"
        fixture_file.write_text(json.dumps(fixtures), encoding="utf-8")
        monkeypatch.setenv("HARNESS_MOCK_FIXTURE_PATH", str(fixture_file))

        engine = MockEngine()
        response = engine.dispatch("does not match anything", "", {})
        assert response.success is True
        # Falls through to worker stub
        assert "FILE: mock-out-1.txt" in response.text
        assert ">>>>>>> REPLACE" in response.text

    def test_fixture_file_ignores_broken_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixture_file = tmp_path / "bad.json"
        fixture_file.write_text("not json", encoding="utf-8")
        monkeypatch.setenv("HARNESS_MOCK_FIXTURE_PATH", str(fixture_file))

        engine = MockEngine()
        response = engine.dispatch("anything", "", {})
        assert response.success is True
        # Falls through to worker stub
        assert "FILE: mock-out-1.txt" in response.text
        assert ">>>>>>> REPLACE" in response.text

    def test_mock_response_set_exists(self) -> None:
        rs = MockResponseSet(fixtures={"a": "b"})
        assert rs.fixtures == {"a": "b"}

    def test_default_waveplan_stub_is_valid_json_block(self) -> None:
        text = _default_waveplan_stub("")
        assert text.startswith("```json")
        assert text.endswith("```")
        # Should be parseable JSON inside the fences
        json_text = text.removeprefix("```json\n").removesuffix("\n```")
        data = json.loads(json_text)
        assert data["schema_version"] == 1
        assert data["integration_strategy"] == "squash"

    def test_default_worker_stub_format(self) -> None:
        text = _default_worker_stub("")
        assert "FILE: mock-out-1.txt" in text
        assert "<<<<<<< SEARCH" in text
        assert "=======" in text
        assert ">>>>>>> REPLACE" in text
        assert "hello from MockEngine" in text


class TestMockEngineFactory:
    def test_get_engine_returns_mock_engine(self) -> None:
        engine = get_engine("mock")
        assert isinstance(engine, MockEngine)
        assert engine.name == "mock"

    def test_mock_in_supported_backends(self) -> None:
        assert "mock" in SUPPORTED_BACKENDS


class TestMockEngineEndToEnd:
    @pytest.fixture
    def tmp_packet(self, tmp_path: Path) -> str:
        p = tmp_path / "packet.md"
        p.write_text("# Hello", encoding="utf-8")
        return str(p)

    @pytest.fixture
    def mock_dispatcher_deps(self, tmp_packet: str):
        adapter = AdapterConfig(
            name="valid-project",
            project_root="{{PROJECT_ROOT}}",
            status_tracking=StatusTrackingConfig(
                backend="csv", config={"csv_path": "status.csv"}
            ),
            observer=ObserverConfig(
                enabled=True,
                cadence_minutes=30,
                daily_retro_time="17:00",
                flag_patterns=[".*FAIL.*"],
            ),
            routing_rules=[],
        )
        with patch("harness.engines.dispatcher.state_db") as mock_db:
            mock_db.insert_dispatch.return_value = "disp-mock-123"
            with patch("harness.engines.dispatcher.state_files") as mock_sf:
                mock_sf.read_engine_health.return_value = {}
                mock_sf.read_active_dispatches.return_value = []
                with patch("harness.engines.dispatcher.jsonl_log"):
                    with patch(
                        "harness.engines.dispatcher.load_project_adapter",
                        return_value=adapter,
                    ):
                        yield

    def test_dispatch_packet_force_engine_mock(
        self,
        tmp_packet: str,
        mock_dispatcher_deps: None,
    ) -> None:
        result = dispatch_packet(
            project="valid-project",
            packet_path=tmp_packet,
            force_engine="mock",
        )
        assert result.success is True
        assert result.engine_used == "mock"
        assert result.fallback_chain == ["mock"]
        assert result.error is None
        assert result.text is not None
        assert "FILE: mock-out-1.txt" in result.text
        assert ">>>>>>> REPLACE" in result.text
