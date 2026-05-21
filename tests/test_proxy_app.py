"""Tests for harness.proxy.app — FastAPI proxy endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness.proxy.app import create_app
from harness.proxy.state import CircuitState, ProxyState, read_state


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


class _FakeClient:
    def __init__(self, status_code: int = 200, content: bytes = b"{}"):
        self._status_code = status_code
        self._content = content

    async def post(self, url: str, **kwargs) -> _FakeResponse:
        return _FakeResponse(self._status_code, self._content)

    async def aclose(self) -> None:
        pass


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    state_path = tmp_path / "proxy_state.json"
    app = create_app(
        state_path=state_path,
        keys={"k1": "sk-fake1", "k2": "sk-fake2"},
        http_client=_FakeClient(),
    )
    return TestClient(app)


def test_happy_path_forwards_request(client: TestClient) -> None:
    resp = client.post("/v1/chat/completions", json={"model": "kimi", "messages": []})
    assert resp.status_code == 200


def test_503_when_no_routable_keys(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = tmp_path / "proxy_state.json"
    app = create_app(
        state_path=state_path,
        keys={"k1": "sk-fake1"},
        http_client=_FakeClient(),
    )
    from harness.proxy.state import KeyState, write_state
    write_state(ProxyState(
        started_at=datetime.now(timezone.utc).isoformat(),
        keys={"k1": KeyState(key_alias="k1", in_flight=6, max_concurrent=6)},
    ), state_path)
    tc = TestClient(app)
    resp = tc.post("/v1/chat/completions", json={"model": "kimi", "messages": []})
    assert resp.status_code == 503


def test_in_flight_increments_and_decrements(client: TestClient, tmp_path: Path) -> None:
    resp = client.post("/v1/chat/completions", json={"model": "kimi", "messages": []})
    assert resp.status_code == 200
    state = read_state(tmp_path / "proxy_state.json")
    total_dispatched = sum(k.total_dispatched for k in state.keys.values())
    assert total_dispatched == 1
    for k in state.keys.values():
        assert k.in_flight == 0


def test_auth_failure_trips_circuit(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = tmp_path / "proxy_state.json"
    app = create_app(
        state_path=state_path,
        keys={"k1": "sk-fake1"},
        http_client=_FakeClient(status_code=401, content=b'{"error":"unauthorized"}'),
    )
    tc = TestClient(app)
    resp = tc.post("/v1/chat/completions", json={"model": "kimi", "messages": []})
    assert resp.status_code == 401
    state = read_state(state_path)
    assert state.keys["k1"].circuit_state == CircuitState.OPEN
    assert state.keys["k1"].permanent is True


def test_byte_for_byte_passthrough(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    body = b'{"choices":[{"message":{"content":"hello"}}]}'
    app = create_app(
        state_path=tmp_path / "proxy_state.json",
        keys={"k1": "sk-fake1"},
        http_client=_FakeClient(status_code=200, content=body),
    )
    tc = TestClient(app)
    resp = tc.post("/v1/chat/completions", json={"model": "kimi", "messages": []})
    assert resp.content == body
