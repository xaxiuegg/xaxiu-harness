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
    _audit_routing_change,
    _eligible_engines,
    _map_error_to_outcome,
    _pick_initial_engine,
    _read_packet,
    _remove_active_dispatch,
    _resolve_burst_engine,
    _resolve_locked_engine,
    _update_active_dispatch_fallback,
    dispatch_packet,
)
from harness.state.files import ActiveDispatch, EngineHealth, StateFileCorruptError


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
    # "mock" is unconditionally excluded by _eligible_engines (test-only backend)
    # 2026-05-22: mimo added to SUPPORTED_BACKENDS (Xiaomi MiMo open platform)
    result = _eligible_engines(health, exclude=set())
    names = [n for n, _ in result]
    assert names == ["kimi", "deepseek", "gemini", "mimo", "anthropic"]


def test_eligible_engines_excludes_tried() -> None:
    health = {
        "deepseek": EngineHealth(priority="HIGH"),
        "kimi": EngineHealth(priority="NORMAL"),
    }
    result = _eligible_engines(health, exclude={"deepseek"})
    names = [n for n, _ in result]
    assert names == ["kimi", "anthropic", "gemini", "mimo"]


def test_eligible_engines_defaults_to_normal() -> None:
    health: dict[str, EngineHealth] = {}
    result = _eligible_engines(health, exclude=set())
    names = [n for n, _ in result]
    assert names == ["deepseek", "kimi", "anthropic", "gemini", "mimo"]


def test_eligible_engines_excludes_mock_unconditionally() -> None:
    """Mock is a test-only backend — never in the auto-fallback chain."""
    health: dict[str, EngineHealth] = {}
    result = _eligible_engines(health, exclude=set())
    names = [n for n, _ in result]
    assert "mock" not in names


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
    assert result.fallback_chain == ["deepseek", "kimi", "anthropic", "gemini", "mimo"]
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
    # deepseek tried once; fallback chains through kimi/anthropic/gemini/mimo
    assert len(result.fallback_chain) == 5
    assert len(set(result.fallback_chain)) == 5  # all unique


# ---------------------------------------------------------------------------
# WIRE-BYPASS-CHAIN (2026-05-22) — force_engine + bypass_chain
# ---------------------------------------------------------------------------

def test_dispatch_bypass_chain_returns_on_first_failure(
    tmp_packet: str, mock_db, mock_state_files, mock_jsonl, mock_load_adapter,
) -> None:
    """bypass_chain=True + force_engine: do NOT iterate the fallback chain."""

    def _fail(*_args, **_kwargs) -> EngineResponse:
        return EngineResponse(success=False, text="", latency_ms=7, error="timeout")

    with patch("harness.engines.dispatcher.get_engine",
               return_value=MagicMock(dispatch=_fail)):
        result = dispatch_packet(
            project="valid-project", packet_path=tmp_packet,
            force_engine="deepseek", bypass_chain=True,
        )

    assert result.success is False
    assert result.engine_used == "deepseek"
    assert result.fallback_chain == ["deepseek"]  # ONLY deepseek tried
    assert "force_engine_failed_no_fallback" in (result.error or "")


def test_dispatch_bypass_chain_off_still_iterates(
    tmp_packet: str, mock_db, mock_state_files, mock_jsonl, mock_load_adapter,
) -> None:
    """Default behaviour preserved: without bypass_chain, the chain fires."""

    def _fail(*_args, **_kwargs) -> EngineResponse:
        return EngineResponse(success=False, text="", latency_ms=7, error="timeout")

    with patch("harness.engines.dispatcher.get_engine",
               return_value=MagicMock(dispatch=_fail)):
        result = dispatch_packet(
            project="valid-project", packet_path=tmp_packet,
            force_engine="deepseek",  # bypass_chain default False
        )

    assert result.success is False
    # Fell through the full production chain
    assert len(result.fallback_chain) >= 4


def test_dispatch_visible_substitution_warning(
    tmp_packet: str, mock_db, mock_state_files, mock_jsonl, mock_load_adapter,
    caplog,
) -> None:
    """WIRE-FORCE-ENGINE-VISIBILITY: when force_engine != engine_used (fallback
    fired and succeeded), emit a WARNING so silent substitution surfaces."""
    import logging
    call_count = 0

    def _fail_first_succeed_after(*_args, **_kwargs) -> EngineResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return EngineResponse(success=False, text="", latency_ms=5, error="timeout")
        return EngineResponse(success=True, text="OK", latency_ms=10, error=None)

    with caplog.at_level(logging.WARNING, logger="harness.engines.dispatcher"):
        with patch("harness.engines.dispatcher.get_engine",
                   return_value=MagicMock(dispatch=_fail_first_succeed_after)):
            result = dispatch_packet(
                project="valid-project", packet_path=tmp_packet,
                force_engine="deepseek",
            )

    assert result.success is True
    assert result.engine_used != "deepseek"  # fallback served the request
    assert any("force_engine" in r.message and "deepseek" in r.message
               for r in caplog.records), (
        f"expected fallback WARNING in logs; got: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# WIRE-LONGFORM-AVOID-KIMI (2026-05-22) — auto-route long packets off Kimi
# ---------------------------------------------------------------------------

def test_dispatch_longform_auto_reroutes_kimi_to_mimo(
    mock_db, mock_state_files, mock_jsonl, mock_load_adapter,
    caplog,
) -> None:
    """Packet >4KB on Kimi → silent re-route to mimo + INFO log."""
    import logging
    import tempfile, os
    # Build a >4KB packet
    fd, big_path = tempfile.mkstemp(suffix=".md", text=True)
    Path(big_path).write_text("x " * 3000, encoding="utf-8")  # ~6KB
    os.close(fd)

    try:
        # Set kimi as HIGH priority so it's the initial engine
        mock_state_files.read_engine_health.return_value = {
            "kimi": EngineHealth(priority="HIGH"),
        }
        with caplog.at_level(logging.INFO, logger="harness.engines.dispatcher"):
            with patch("harness.engines.dispatcher.get_engine",
                       return_value=MagicMock(dispatch=MagicMock(return_value=EngineResponse(
                           success=True, text="OK", latency_ms=10, error=None,
                       )))):
                result = dispatch_packet(project="valid-project", packet_path=big_path)

        # The re-route message should be present
        assert any("kimi" in r.message and "mimo" in r.message for r in caplog.records), (
            f"expected reroute log; got: {[r.message for r in caplog.records]}"
        )
    finally:
        Path(big_path).unlink(missing_ok=True)


def test_dispatch_longform_respects_explicit_force_engine_kimi(
    mock_db, mock_state_files, mock_jsonl, mock_load_adapter,
    caplog,
) -> None:
    """force_engine=kimi on long packet → keep kimi + WARNING log."""
    import logging
    import tempfile, os
    fd, big_path = tempfile.mkstemp(suffix=".md", text=True)
    Path(big_path).write_text("x " * 3000, encoding="utf-8")
    os.close(fd)

    try:
        with caplog.at_level(logging.WARNING, logger="harness.engines.dispatcher"):
            with patch("harness.engines.dispatcher.get_engine",
                       return_value=MagicMock(dispatch=MagicMock(return_value=EngineResponse(
                           success=True, text="OK", latency_ms=10, error=None,
                       )))):
                result = dispatch_packet(
                    project="valid-project", packet_path=big_path,
                    force_engine="kimi",
                )

        # Operator's force_engine respected; ~60s warning emitted
        assert result.engine_used == "kimi"
        assert any("force_engine=kimi" in r.message and "long-form" in r.message
                   for r in caplog.records)
    finally:
        Path(big_path).unlink(missing_ok=True)


def test_dispatch_short_packet_no_rerouting(
    tmp_packet, mock_db, mock_state_files, mock_jsonl, mock_load_adapter,
    caplog,
) -> None:
    """Sub-threshold packet should leave routing untouched."""
    import logging
    with caplog.at_level(logging.INFO, logger="harness.engines.dispatcher"):
        with patch("harness.engines.dispatcher.get_engine",
                   return_value=MagicMock(dispatch=MagicMock(return_value=EngineResponse(
                       success=True, text="OK", latency_ms=10, error=None,
                   )))):
            dispatch_packet(project="valid-project", packet_path=tmp_packet)
    # No re-route message for a small packet
    assert not any("kimi → mimo" in r.message for r in caplog.records)


# ── _map_error_to_outcome ────────────────────────────────────────────────

def test_map_error_to_outcome_timeout() -> None:
    assert _map_error_to_outcome("timeout") == "timeout"


def test_map_error_to_outcome_api_error() -> None:
    assert _map_error_to_outcome("HTTP 500") == "api_error"
    assert _map_error_to_outcome(None) == "api_error"


# ── _audit_routing_change ────────────────────────────────────────────────

def test_audit_routing_change_swallows_exception() -> None:
    with patch(
        "harness.engines.dispatcher.state_db.insert_routing_change",
        side_effect=RuntimeError("db locked"),
    ):
        _audit_routing_change("lock", "deepseek")


# ── _remove_active_dispatch / _update_active_dispatch_fallback ───────────

def test_remove_active_dispatch_swallows_exception() -> None:
    with patch(
        "harness.engines.dispatcher.state_files.read_active_dispatches",
        side_effect=RuntimeError("boom"),
    ):
        _remove_active_dispatch("disp-123")


def test_update_active_dispatch_fallback_success() -> None:
    entry = ActiveDispatch(
        dispatch_id="disp-123",
        project="p",
        packet_path="pkt",
        backend="deepseek",
        started_at="2024-01-01T00:00:00+00:00",
        status="running",
        fallback_count=0,
        current_backend="deepseek",
    )
    with patch(
        "harness.engines.dispatcher.state_files.read_active_dispatches",
        return_value=[entry],
    ):
        with patch(
            "harness.engines.dispatcher.state_files.write_active_dispatches"
        ) as mock_write:
            _update_active_dispatch_fallback("disp-123", "kimi")
            mock_write.assert_called_once()
            written = mock_write.call_args[0][0]
            assert written[0].current_backend == "kimi"
            assert written[0].fallback_count == 1
            assert written[0].status == "fallback"


def test_update_active_dispatch_fallback_swallows_exception() -> None:
    with patch(
        "harness.engines.dispatcher.state_files.read_active_dispatches",
        side_effect=RuntimeError("boom"),
    ):
        _update_active_dispatch_fallback("disp-123", "kimi")


# ── _pick_initial_engine burst routing ───────────────────────────────────

def test_pick_initial_engine_routing_rule_burst_active(
    minimal_adapter: AdapterConfig,
) -> None:
    adapter = minimal_adapter.model_copy(
        update={
            "routing_rules": [
                RoutingRule(if_="*.md", then=RoutingAction(backend="burst"))
            ]
        }
    )
    health = {"kimi": EngineHealth(burst_until="2099-01-01T00:00:00+00:00")}
    result = _pick_initial_engine(adapter, health, "foo.md", None)
    assert result[0] == "kimi"


def test_pick_initial_engine_routing_rule_burst_expired(
    minimal_adapter: AdapterConfig,
) -> None:
    adapter = minimal_adapter.model_copy(
        update={
            "routing_rules": [
                RoutingRule(if_="*.md", then=RoutingAction(backend="burst"))
            ]
        }
    )
    health = {}
    result = _pick_initial_engine(adapter, health, "foo.md", None)
    assert result[0] == "deepseek"


# ── dispatch_packet – engine health corrupt ──────────────────────────────

def test_dispatch_engine_health_corrupt(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    mock_state_files.StateFileCorruptError = StateFileCorruptError
    mock_state_files.read_engine_health.side_effect = StateFileCorruptError(
        Path("engine_health.json")
    )
    result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is False
    assert "engine_health_corrupt" in result.error
    mock_db.insert_dispatch.assert_not_called()


# ── dispatch_packet – engine selection failed ────────────────────────────

def test_dispatch_engine_selection_failed(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    with patch(
        "harness.engines.dispatcher._pick_initial_engine",
        side_effect=RuntimeError("boom"),
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is False
    assert "engine_selection_failed" in result.error


# ── dispatch_packet – db insert failed ───────────────────────────────────

def test_dispatch_db_insert_failed(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
    mock_get_engine,
) -> None:
    mock_db.insert_dispatch.side_effect = RuntimeError("db locked")
    result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is False
    assert "db_insert_failed" in result.error
    assert result.engine_used == "deepseek"
    assert result.fallback_chain == ["deepseek"]
    assert result.dispatch_id == ""


# ── dispatch_packet – append active dispatch swallowed ───────────────────

def test_dispatch_append_active_dispatch_failure_swallowed(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    mock_state_files.append_active_dispatch.side_effect = RuntimeError("disk full")
    result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is True


# ── dispatch_packet – wave_id status hooks ───────────────────────────────

def test_dispatch_wave_id_status_hooks_success(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    with patch("harness.status.hooks") as mock_hooks:
        result = dispatch_packet(
            project="valid-project", packet_path=tmp_packet, wave_id="W1-TEST"
        )
    assert result.success is True
    mock_hooks.on_dispatch_start.assert_called_once_with(
        task_id="disp-1234", wave_id="W1-TEST", engine="deepseek"
    )
    mock_hooks.on_dispatch_complete.assert_called_once_with(
        task_id="disp-1234", wave_id="W1-TEST", outcome="success"
    )


def test_dispatch_wave_id_hooks_raise_start(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    with patch("harness.status.hooks") as mock_hooks:
        mock_hooks.on_dispatch_start.side_effect = RuntimeError("boom")
        result = dispatch_packet(
            project="valid-project", packet_path=tmp_packet, wave_id="W1-TEST"
        )
    assert result.success is True
    mock_hooks.on_dispatch_complete.assert_called_once_with(
        task_id="disp-1234", wave_id="W1-TEST", outcome="success"
    )


def test_dispatch_wave_id_hooks_raise_complete(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    with patch("harness.status.hooks") as mock_hooks:
        mock_hooks.on_dispatch_complete.side_effect = RuntimeError("boom")
        result = dispatch_packet(
            project="valid-project", packet_path=tmp_packet, wave_id="W1-TEST"
        )
    assert result.success is True
    mock_hooks.on_dispatch_start.assert_called_once()


# ── dispatch_packet – jsonl / db exception swallowing (success path) ─────

def test_dispatch_update_status_failure_swallowed_success(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    mock_db.update_dispatch_status.side_effect = RuntimeError("db locked")
    result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is True


def test_dispatch_jsonl_log_failure_swallowed_success(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_get_engine,
    mock_load_adapter,
) -> None:
    mock_jsonl.write_log_entry.side_effect = RuntimeError("disk full")
    result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is True


def test_dispatch_update_health_failure_swallowed(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
    mock_get_engine,
) -> None:
    mock_state_files.update_engine_health.side_effect = RuntimeError("disk full")
    mock_get_engine.return_value.dispatch.return_value = EngineResponse(
        success=False, text="", latency_ms=5, error="timeout"
    )
    result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is False
    assert "all_fallbacks_exhausted" in result.error


# ── dispatch_packet – locked engine + wave_id ────────────────────────────

def test_dispatch_locked_engine_wave_id_hooks(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    mock_state_files.read_engine_health.return_value = {
        "deepseek": EngineHealth(locked=True),
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
        with patch("harness.status.hooks") as mock_hooks:
            result = dispatch_packet(
                project="valid-project", packet_path=tmp_packet, wave_id="W1-TEST"
            )
    assert result.success is False
    assert "locked_engine_failed" in result.error
    mock_hooks.on_dispatch_start.assert_called_once_with(
        task_id="disp-1234", wave_id="W1-TEST", engine="deepseek"
    )
    mock_hooks.on_dispatch_complete.assert_called_once_with(
        task_id="disp-1234",
        wave_id="W1-TEST",
        outcome="failure",
        notes="locked_engine_failed: HTTP 503",
    )


def test_dispatch_update_status_failure_locked_engine(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    mock_state_files.read_engine_health.return_value = {
        "deepseek": EngineHealth(locked=True),
    }
    mock_db.update_dispatch_status.side_effect = RuntimeError("db locked")
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
    assert "locked_engine_failed" in result.error


def test_dispatch_jsonl_log_failure_locked_engine(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    mock_state_files.read_engine_health.return_value = {
        "deepseek": EngineHealth(locked=True),
    }
    mock_jsonl.write_log_entry.side_effect = RuntimeError("disk full")
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
    assert "locked_engine_failed" in result.error


# ── dispatch_packet – all fallbacks exhausted + wave_id ──────────────────

def test_dispatch_all_fallbacks_exhausted_wave_id_hooks(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    with patch(
        "harness.engines.dispatcher.get_engine",
        return_value=MagicMock(
            dispatch=MagicMock(
                return_value=EngineResponse(
                    success=False, text="", latency_ms=5, error="timeout"
                )
            )
        ),
    ):
        with patch("harness.status.hooks") as mock_hooks:
            result = dispatch_packet(
                project="valid-project", packet_path=tmp_packet, wave_id="W1-TEST"
            )
    assert result.success is False
    assert "all_fallbacks_exhausted" in result.error
    mock_hooks.on_dispatch_start.assert_called_once_with(
        task_id="disp-1234", wave_id="W1-TEST", engine="deepseek"
    )
    mock_hooks.on_dispatch_complete.assert_called_once_with(
        task_id="disp-1234",
        wave_id="W1-TEST",
        outcome="failure",
        notes="all_fallbacks_exhausted: timeout",
    )


def test_dispatch_update_status_failure_all_fallbacks(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    mock_db.update_dispatch_status.side_effect = RuntimeError("db locked")
    with patch(
        "harness.engines.dispatcher.get_engine",
        return_value=MagicMock(
            dispatch=MagicMock(
                return_value=EngineResponse(
                    success=False, text="", latency_ms=5, error="timeout"
                )
            )
        ),
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is False
    assert "all_fallbacks_exhausted" in result.error


def test_dispatch_jsonl_log_failure_all_fallbacks(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    mock_jsonl.write_log_entry.side_effect = RuntimeError("disk full")
    with patch(
        "harness.engines.dispatcher.get_engine",
        return_value=MagicMock(
            dispatch=MagicMock(
                return_value=EngineResponse(
                    success=False, text="", latency_ms=5, error="timeout"
                )
            )
        ),
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is False
    assert "all_fallbacks_exhausted" in result.error


# ── dispatch_packet – fallback step exception swallowing ─────────────────

def test_dispatch_insert_fallback_failure_swallowed(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    mock_db.insert_fallback.side_effect = RuntimeError("db locked")
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
    with patch(
        "harness.engines.dispatcher.get_engine",
        side_effect=lambda name: engines[name],
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is True
    assert result.engine_used == "kimi"
    assert result.fallback_chain == ["deepseek", "kimi"]


def test_dispatch_jsonl_log_failure_fallback(
    tmp_packet: str,
    mock_db,
    mock_state_files,
    mock_jsonl,
    mock_load_adapter,
) -> None:
    mock_jsonl.write_log_entry.side_effect = RuntimeError("disk full")
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
    with patch(
        "harness.engines.dispatcher.get_engine",
        side_effect=lambda name: engines[name],
    ):
        result = dispatch_packet(project="valid-project", packet_path=tmp_packet)
    assert result.success is True
    assert result.engine_used == "kimi"
