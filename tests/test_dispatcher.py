"""Tests for src.harness.engines.dispatcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.schema import AdapterConfig, RoutingAction, RoutingRule
from harness.engines.base import EngineResponse
from harness.engines.dispatcher import (
    MAX_PACKET_BYTES,
    DispatchResult,
    _eligible_engines,
    _pick_initial_engine,
    _read_packet,
    _resolve_burst_engine,
    _resolve_locked_engine,
    dispatch_packet,
)
from harness.state.files import ActiveDispatch, EngineHealth


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_adapter() -> AdapterConfig:
    """Return a minimal AdapterConfig with no routing rules."""
    return AdapterConfig(
        name="test-project",
        project_root="{{PROJECT_ROOT}}",
        status_tracking={"backend": "csv", "config": {"csv_path": "status.csv"}},
        observer={
            "enabled": True,
            "cadence_minutes": 30,
            "daily_retro_time": "17:00",
            "flag_patterns": [".*FAIL.*"],
        },
        routing_rules=[],
    )


@pytest.fixture
def tmp_packet(tmp_path: Path) -> str:
    """Create a small packet file and return its path."""
    p = tmp_path / "packet.md"
    p.write_text("# Hello", encoding="utf-8")
    return str(p)


@pytest.fixture
def mock_engine() -> MagicMock:
    """Return a mock engine that succeeds by default."""
    engine = MagicMock()
    engine.dispatch.return_value = EngineResponse(
        success=True, text="ok", latency_ms=42, error=None
    )
    return engine


@pytest.fixture
def mock_db():
    """Patch all state_db functions."""
    with patch("harness.engines.dispatcher.state_db") as m:
        m.insert_dispatch.return_value = "disp-1234"
        yield m


@pytest.fixture
def mock_state_files():
    """Patch all state_files functions."""
    with patch("harness.engines.dispatcher.state_files") as m:
        m.read_engine_health.return_value = {}
        m.read_active_dispatches.return_value = []
        yield m


@pytest.fixture
def mock_jsonl():
    """Patch jsonl_log.write_log_entry."""
    with patch("harness.engines.dispatcher.jsonl_log") as m:
        yield m


@pytest.fixture
def mock_get_engine(mock_engine: MagicMock):
    """Patch get_engine to return the mock engine."""
    with patch("harness.engines.dispatcher.get_engine", return_value=mock_engine) as m:
        yield m


@pytest.fixture
def mock_load_adapter(minimal_adapter: AdapterConfig):
    """Patch load_project_adapter to return the minimal adapter."""
    with patch(
        "harness.engines.dispatcher.load_project_adapter", return_value=minimal_adapter
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# _read_packet
# ---------------------------------------------------------------------------

def test_read_packet_success(tmp_path: Path) -> None:
    p = tmp_path / "small.md"
    p.write_text("hello", encoding="utf-8")
    assert _read_packet(str(p)) == "hello"


def test_read_packet_too_large(tmp_path: Path) -> None:
    p = tmp_path / "huge.md"
    p.write_bytes(b"x" * (MAX_PACKET_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds limit"):
        _read_packet(str(p))


# ---------------------------------------------------------------------------
# _eligible_engines
# ---------------------------------------------------------------------------

def test_eligible_engines_sorts_by_priority() -> None:
    health = {
        "deepseek": EngineHealth(priority="NORMAL"),
        "kimi": EngineHealth(priority="HIGH"),
        "anthropic": EngineHealth(priority="AVOID"),
    }
    result = _eligible_engines(health, exclude=set())
    names = [n for n, _ in result]
    assert names == ["kimi", "deepseek", "gemini", "anthropic"]


def test_eligible_engines_excludes_tried() -> None:
    health = {
        "deepseek": EngineHealth(priority="HIGH"),
        "kimi": EngineHealth(priority="NORMAL"),
    }
    result = _eligible_engines(health, exclude={"deepseek"})
    names = [n for n, _ in result]
    assert names == ["kimi", "anthropic", "gemini"]


def test_eligible_engines_defaults_to_normal() -> None:
    health: dict[str, EngineHealth] = {}
    result = _eligible_engines(health, exclude=set())
    names = [n for n, _ in result]
    assert names == ["deepseek", "kimi", "anthropic", "gemini"]


# ---------------------------------------------------------------------------
# _resolve_locked_engine
# ---------------------------------------------------------------------------

def test_resolve_locked_engine_none() -> None:
    health: dict[str, EngineHealth] = {}
    assert _resolve_locked_engine(health) is None


def test_resolve_locked_engine_returns_locked() -> None:
    health = {
        "deepseek": EngineHealth(locked=True, priority="NORMAL"),
        "kimi": EngineHealth(locked=False),
    }
    assert _resolve_locked_engine(health) == "deepseek"


def test_resolve_locked_engine_prefers_high_priority() -> None:
    health = {
        "deepseek": EngineHealth(locked=True, priority="NORMAL"),
        "kimi": EngineHealth(locked=True, priority="HIGH"),
    }
    assert _resolve_locked_engine(health) == "kimi"


# ---------------------------------------------------------------------------
# _resolve_burst_engine
# ---------------------------------------------------------------------------

def test_resolve_burst_engine_none() -> None:
    health: dict[str, EngineHealth] = {}
    assert _resolve_burst_engine(health) is None


def test_resolve_burst_engine_expired() -> None:
    health = {
        "deepseek": EngineHealth(burst_until="2000-01-01T00:00:00+00:00"),
    }
    assert _resolve_burst_engine(health) is None


def test_resolve_burst_engine_active() -> None:
    # Use a far-future date so the burst is definitely active
    health = {
        "deepseek": EngineHealth(burst_until="2099-01-01T00:00:00+00:00"),
    }
    assert _resolve_burst_engine(health) == "deepseek"


# ---------------------------------------------------------------------------
# _pick_initial_engine
# ---------------------------------------------------------------------------

def test_pick_initial_engine_force_engine(minimal_adapter: AdapterConfig) -> None:
    result = _pick_initial_engine(minimal_adapter, {}, "packet.md", "kimi")
    assert result == ("kimi", None, {})


def test_pick_initial_engine_lock(minimal_adapter: AdapterConfig) -> None:
    health = {"deepseek": EngineHealth(locked=True)}
    result = _pick_initial_engine(minimal_adapter, health, "packet.md", None)
    assert result[0] == "deepseek"


def test_pick_initial_engine_burst(minimal_adapter: AdapterConfig) -> None:
    health = {"kimi": EngineHealth(burst_until="2099-01-01T00:00:00+00:00")}
    result = _pick_initial_engine(minimal_adapter, health, "packet.md", None)
    assert result[0] == "kimi"


def test_pick_initial_engine_routing_rule(minimal_adapter: AdapterConfig) -> None:
    adapter = minimal_adapter.model_copy(
        update={
            "routing_rules": [
                RoutingRule(if_="*.md", then=RoutingAction(backend="anthropic"))
            ]
        }
    )
    result = _pick_initial_engine(adapter, {}, "foo.md", None)
    assert result == ("anthropic", None, {})


def test_pick_initial_engine_routing_rule_avoid_skip(minimal_adapter: AdapterConfig) -> None:
    adapter = minimal_adapter.model_copy(
        update={
            "routing_rules": [
                RoutingRule(if_="*.md", then=RoutingAction(backend="deepseek"))
            ]
        }
    )
    health = {
        "deepseek": EngineHealth(priority="AVOID"),
        "kimi": EngineHealth(priority="HIGH"),
    }
    result = _pick_initial_engine(adapter, health, "foo.md", None)
    assert result[0] == "kimi"


def test_pick_initial_engine_global_priority(minimal_adapter: AdapterConfig) -> None:
    health = {
        "kimi": EngineHealth(priority="HIGH"),
        "deepseek": EngineHealth(priority="NORMAL"),
    }
    result = _pick_initial_engine(minimal_adapter, health, "foo.txt", None)
    assert result[0] == "kimi"


# ---------------------------------------------------------------------------
# dispatch_packet – error paths
# ---------------------------------------------------------------------------

def test_dispatch_invalid_project(mock_db, mock_state_files, mock_jsonl) -> None:
    result = dispatch_packet(project="BAD NAME", packet_path="/dev/null")
    assert result.success is False
    assert result.error == "invalid_project_name"
    mock_db.insert_dispatch.assert_not_called()


def test_dispatch_unsupported_force_engine(
    mock_db, mock_state_files, mock_jsonl
) -> None:
    result = dispatch_packet(
        project="valid-project",
        packet_path="/dev/null",
        force_engine="not-an-engine",
    )
    assert result.success is False
    assert result.error == "unsupported_force_engine"
    mock_db.insert_dispatch.assert_not_called()


def test_dispatch_adapter_load_failure(
    mock_db, mock_state_files, mock_jsonl
) -> None:
    with patch(
        "harness.engines.dispatcher.load_project_adapter",
        side_effect=FileNotFoundError("missing"),
    ):
        result = dispatch_packet(project="valid-project", packet_path="/dev/null")
    assert result.success is False
    assert "adapter_load_failed" in result.error
    mock_db.insert_dispatch.assert_not_called()


def test_dispatch_packet_read_failure(
    mock_db, mock_state_files, mock_jsonl
) -> None:
    with patch(
        "harness.engines.dispatcher.load_project_adapter",
        return_value=AdapterConfig(
            name="valid-project",
            project_root="{{PROJECT_ROOT}}",
            status_tracking={"backend": "csv", "config": {"csv_path": "status.csv"}},
            observer={
                "enabled": True,
                "cadence_minutes": 30,
                "daily_retro_time": "17:00",
                "flag_patterns": [".*FAIL.*"],
            },
            routing_rules=[],
        ),
    ):
        result = dispatch_packet(project="valid-project", packet_path="/nonexistent")
    assert result.success is False
    assert "packet_read_failed" in result.error
    mock_db.insert_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch_packet – success path
# ---------------------------------------------------------------------------

def test_dispatch_success(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    result = dispatch_packet(project="valid-project", packet_path=tmp_packet)

    assert isinstance(result, DispatchResult)
    assert result.success is True
    assert result.engine_used == "deepseek"
    assert result.fallback_chain == ["deepseek"]
    assert result.text == "ok"
    assert result.error is None
    assert result.dispatch_id == "disp-1234"

    mock_db.insert_dispatch.assert_called_once()
    mock_db.update_dispatch_status.assert_called_once_with(
        "disp-1234", "success", latency_ms=42
    )
    mock_jsonl.write_log_entry.assert_called_once()
    args = mock_jsonl.write_log_entry.call_args.kwargs
    assert args["outcome"] == "success"
    assert args["backend"] == "deepseek"


# ---------------------------------------------------------------------------
# dispatch_packet – fallback path
# ---------------------------------------------------------------------------

def test_dispatch_fallback_then_success(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    """deepseek fails, kimi succeeds."""
    engines = {
        "deepseek": MagicMock(
            dispatch=MagicMock(
                return_value=EngineResponse(
                    success=False, text="", latency_ms=10, error="HTTP 500"
                )
            )
        ),
        "kimi": MagicMock(
            dispatch=MagicMock(
                return_value=EngineResponse(
                    success=True, text="fallback ok", latency_ms=20, error=None
                )
            )
        ),
    }

    def _get_engine(name: str) -> MagicMock:
        return engines[name]

    with patch("harness.engines.dispatcher.get_engine", side_effect=_get_engine):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)

    assert result.success is True
    assert result.engine_used == "kimi"
    assert result.fallback_chain == ["deepseek", "kimi"]
    assert result.text == "fallback ok"

    mock_db.insert_fallback.assert_called_once_with(
        "disp-1234",
        from_backend="deepseek",
        to_backend="kimi",
        reason="HTTP 500",
    )

    # jsonl should have a fallback entry AND a success entry
    calls = mock_jsonl.write_log_entry.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["outcome"] == "fallback"
    assert calls[0].kwargs["fallback_to"] == "kimi"
    assert calls[1].kwargs["outcome"] == "success"


# ---------------------------------------------------------------------------
# dispatch_packet – all fallbacks exhausted
# ---------------------------------------------------------------------------

def test_dispatch_all_fallbacks_exhausted(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    """All engines fail."""

    def _failing_dispatch(*_args, **_kwargs) -> EngineResponse:
        return EngineResponse(success=False, text="", latency_ms=5, error="timeout")

    with patch(
        "harness.engines.dispatcher.get_engine",
        return_value=MagicMock(dispatch=_failing_dispatch),
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)

    assert result.success is False
    assert result.fallback_chain == ["deepseek", "kimi", "anthropic", "gemini"]
    assert "all_fallbacks_exhausted" in result.error
    mock_db.update_dispatch_status.assert_called_with(
        "disp-1234", "all_fallbacks_exhausted", latency_ms=5
    )


# ---------------------------------------------------------------------------
# dispatch_packet – LOCK refusal
# ---------------------------------------------------------------------------

def test_dispatch_locked_engine_no_fallback(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    """Locked engine fails and no other engine is locked → total failure."""
    mock_state_files.read_engine_health.return_value = {
        "deepseek": EngineHealth(locked=True),
        "kimi": EngineHealth(),
    }

    with patch(
        "harness.engines.dispatcher.get_engine",
        return_value=MagicMock(
            dispatch=MagicMock(
                return_value=EngineResponse(
                    success=False, text="", latency_ms=7, error="HTTP 503"
                )
            )
        ),
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)

    assert result.success is False
    assert result.engine_used == "deepseek"
    assert result.fallback_chain == ["deepseek"]
    assert "locked_engine_failed" in result.error


# ---------------------------------------------------------------------------
# dispatch_packet – force_engine
# ---------------------------------------------------------------------------

def test_dispatch_force_engine(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    result = dispatch_packet(
        project="valid-project",
        packet_path=tmp_packet,
        force_engine="anthropic",
    )
    assert result.success is True
    assert result.engine_used == "anthropic"
    mock_get_engine.assert_called_with("anthropic")


# ---------------------------------------------------------------------------
# dispatch_packet – BURST routing
# ---------------------------------------------------------------------------

def test_dispatch_burst_routing(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    mock_state_files.read_engine_health.return_value = {
        "kimi": EngineHealth(burst_until="2099-01-01T00:00:00+00:00"),
    }
    result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is True
    assert result.engine_used == "kimi"
    mock_get_engine.assert_called_with("kimi")


# ---------------------------------------------------------------------------
# dispatch_packet – routing rule AVOID override audits priority_change
# ---------------------------------------------------------------------------

def test_dispatch_avoid_override_audits(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
) -> None:
    adapter = AdapterConfig(
        name="valid-project",
        project_root="{{PROJECT_ROOT}}",
        status_tracking={"backend": "csv", "config": {"csv_path": "status.csv"}},
        observer={
            "enabled": True,
            "cadence_minutes": 30,
            "daily_retro_time": "17:00",
            "flag_patterns": [".*FAIL.*"],
        },
        routing_rules=[
            RoutingRule(if_="*.md", then=RoutingAction(backend="deepseek"))
        ],
    )
    mock_state_files.read_engine_health.return_value = {
        "deepseek": EngineHealth(priority="AVOID"),
        "kimi": EngineHealth(priority="HIGH"),
    }

    with patch(
        "harness.engines.dispatcher.load_project_adapter", return_value=adapter
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)

    assert result.success is True
    assert result.engine_used == "kimi"
    mock_db.insert_routing_change.assert_called_once()
    args = mock_db.insert_routing_change.call_args
    assert args.kwargs["action"] == "priority_change"
    assert args.kwargs["engine"] == "deepseek"


# ---------------------------------------------------------------------------
# dispatch_packet – engine init failure wrapped safely
# ---------------------------------------------------------------------------

def test_dispatch_engine_init_failure(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    with patch(
        "harness.engines.dispatcher.get_engine",
        side_effect=RuntimeError("API key missing"),
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)

    assert result.success is False
    assert "all_fallbacks_exhausted" in result.error or "locked_engine_failed" in result.error


# ---------------------------------------------------------------------------
# dispatch_packet – no redispath to same engine
# ---------------------------------------------------------------------------

def test_dispatch_no_redispatch_same_engine(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    """Even if an engine is highest priority, it is only tried once."""
    call_count = 0

    def _flaky_dispatch(*_args, **_kwargs) -> EngineResponse:
        nonlocal call_count
        call_count += 1
        return EngineResponse(
            success=False, text="", latency_ms=1, error="err"
        )

    with patch(
        "harness.engines.dispatcher.get_engine",
        return_value=MagicMock(dispatch=_flaky_dispatch),
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)

    assert result.success is False
    # deepseek is tried once; fallback tries kimi then anthropic
    assert len(result.fallback_chain) == 4
    assert len(set(result.fallback_chain)) == 4  # all unique
