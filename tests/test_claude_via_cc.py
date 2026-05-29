"""Tests for the claude-via-cc subscription engine + its `harness ask` wiring.

All MOCKED — zero real subprocess / engine calls. Pins the subscription-auth
behavior (no injected key), the effort flag, and the pool-bypass in ask.py.
"""
import inspect

import pytest

from harness.engines.base import EngineResponse
from harness.engines.claude_code_subprocess import ClaudeViaCcEngine


def _engine() -> ClaudeViaCcEngine:
    return ClaudeViaCcEngine(verify_binary=False)


def test_engine_identity():
    e = _engine()
    assert e.name == "claude-via-cc"
    assert e._subscription is True
    assert e._base_url == ""            # built-in backend (subscription)
    assert e._default_model == "opus"   # Opus 4.8 alias


def test_build_env_omits_key_base_url_and_aliases():
    env = _engine()._build_env()
    # Subscription auth -> Claude Code uses stored `claude login` OAuth, so we
    # inject NO key/token/base_url and do NOT override the model-alias suite.
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL" not in env
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env


def test_build_command_effort_and_model():
    cmd = _engine()._build_command("", {"effort": "MAX"})
    assert "--effort" in cmd
    assert cmd[cmd.index("--effort") + 1] == "max"   # normalized lowercase
    assert cmd[cmd.index("--model") + 1] == "opus"


def test_build_command_no_effort_when_absent():
    assert "--effort" not in _engine()._build_command("", {})


def test_subscription_engine_has_empty_key():
    # The dispatch empty-key guard is `not key and not subscription`; with
    # subscription=True it must NOT fire on the empty key.
    e = _engine()
    assert e._api_key == ""
    assert e._subscription is True


def test_get_engine_needs_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from harness.engines.concrete import get_engine
    e = get_engine("claude-via-cc")
    assert e.name == "claude-via-cc"
    assert e._base_url == ""


def test_metadata_entry():
    from harness.engines.metadata import describe
    m = describe("claude-via-cc")
    assert m.vendor == "anthropic"
    assert m.default_model == "opus"
    assert m.key_env == ""              # no env-var key


def test_ask_dispatch_one_bypasses_pool(monkeypatch):
    """claude-via-cc must dispatch directly (get_engine().dispatch), NOT via
    the multi-key pool (it has no poolable key)."""
    import harness.ask as ask
    import harness.engines.concrete as concrete
    import harness.engines.pool_dispatch as pool

    class _FakeEngine:
        def dispatch(self, q, model, extra):
            assert extra.get("effort") == "high"   # effort flowed through
            return EngineResponse(
                success=True, text="reviewed", latency_ms=10,
                error=None, tokens_in=5, tokens_out=7, cost_usd=0.02,
            )

    monkeypatch.setattr(concrete, "get_engine", lambda name, **kw: _FakeEngine())

    def _boom(*a, **k):
        raise AssertionError(
            "dispatch_with_pool must NOT be called for claude-via-cc"
        )
    monkeypatch.setattr(pool, "dispatch_with_pool", _boom)

    r = ask._dispatch_one("claude-via-cc", "q", 0.30, 180, effort="high")
    assert r.ok is True
    assert r.engine == "claude-via-cc"
    assert r.text == "reviewed"
    assert r.cost_usd == pytest.approx(0.02)
    assert r.winning_alias == "subscription"


def test_effort_threads_through_run_panel(monkeypatch):
    import harness.ask as ask
    from harness.ask import AskResult
    seen = {}

    def _fake(engine, question, mb, ts, *, model_override="", effort=""):
        seen["effort"] = effort
        return AskResult(engine=engine, ok=True, elapsed_s=0.1, tokens_in=1,
                         tokens_out=1, cost_usd=0.0, text="x", error="",
                         winning_alias="", attempt_count=1)

    monkeypatch.setattr(ask, "_dispatch_one", _fake)
    ask.run_panel("q", engines=("claude-via-cc",), effort="xhigh")
    assert seen["effort"] == "xhigh"


def test_effort_present_in_ask_signatures():
    from harness.ask import _dispatch_one, run_panel, run_audit
    for fn in (_dispatch_one, run_panel, run_audit):
        assert "effort" in inspect.signature(fn).parameters
