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

    def _fake(engine, question, mb, ts, *, model_override="", effort="",
              agentic=False):
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


# --- W14-AGENTIC-MODE 2026-05-29: --agentic (non-bare) dispatch profile ---
# Doc-verified (AGENT_REFERENCE tool matrix): WebFetch/WebSearch function
# only on the subscription backend (real Anthropic server tools); provider
# /anthropic endpoints don't expose their native web search (it lives on
# the OpenAI /v1 surface under a different protocol).  So agentic mode is
# subscription-gated.


def test_agentic_drops_bare_and_offers_web_tools():
    cmd = _engine()._build_command("opus", {"agentic": True})
    assert "--bare" not in cmd, "agentic must drop --bare"
    tools = cmd[cmd.index("--tools") + 1]
    assert "WebFetch" in tools and "WebSearch" in tools and "Task" in tools


def test_subscription_non_agentic_drops_bare_keeps_empty_tools():
    # W14-CLAUDE-VIA-CC-AUTH-FIX: subscription can NEVER use --bare (bare
    # ignores CLAUDE_CODE_OAUTH_TOKEN + the /login credential store per
    # code.claude.com/docs/en/authentication), so even the non-agentic
    # single-shot drops --bare.  Tools stay empty (deterministic).
    cmd = _engine()._build_command("opus", {})
    assert "--bare" not in cmd
    assert cmd[cmd.index("--tools") + 1] == ""


def test_subscription_always_drops_bare():
    """Both subscription modes (agentic + non-agentic) must omit --bare."""
    e = _engine()
    assert "--bare" not in e._build_command("opus", {})
    assert "--bare" not in e._build_command("opus", {"agentic": True})


def test_agentic_gated_to_subscription():
    """A stray agentic=True on a NON-subscription (provider) engine must be
    ignored: --bare stays, tools stay empty (no provider token-bloat)."""
    from harness.engines.claude_code_subprocess import (
        ClaudeCodeSubprocessEngine,
    )
    prov = ClaudeCodeSubprocessEngine(
        api_key="x", base_url="https://e/anthropic",
        default_model="m", verify_binary=False,
    )
    cmd = prov._build_command("m", {"agentic": True})
    assert "--bare" in cmd, "provider agentic must stay --bare (gated)"
    assert cmd[cmd.index("--tools") + 1] == ""


def test_provider_keeps_bare_non_agentic():
    """Provider engines auth via the injected ANTHROPIC_API_KEY (which
    --bare DOES read) and keep --bare to suppress the tool-bloat loop."""
    from harness.engines.claude_code_subprocess import (
        ClaudeCodeSubprocessEngine,
    )
    prov = ClaudeCodeSubprocessEngine(
        api_key="x", base_url="https://e/anthropic",
        default_model="m", verify_binary=False,
    )
    assert "--bare" in prov._build_command("m", {})


def test_agentic_composes_with_effort():
    cmd = _engine()._build_command("opus", {"agentic": True, "effort": "max"})
    assert "--bare" not in cmd
    assert "--effort" in cmd and cmd[cmd.index("--effort") + 1] == "max"


def test_agentic_threads_through_run_panel(monkeypatch):
    import harness.ask as ask
    from harness.ask import AskResult
    seen = {}

    def _fake(engine, question, mb, ts, *, model_override="", effort="",
              agentic=False):
        seen["agentic"] = agentic
        return AskResult(engine=engine, ok=True, elapsed_s=0.1, tokens_in=1,
                         tokens_out=1, cost_usd=0.0, text="x", error="",
                         winning_alias="", attempt_count=1)

    monkeypatch.setattr(ask, "_dispatch_one", _fake)
    ask.run_panel("q", engines=("claude-via-cc",), agentic=True)
    assert seen["agentic"] is True


def test_agentic_injected_into_extra(monkeypatch):
    """_dispatch_one(agentic=True) must put agentic=True into the engine's
    extra_args (so _build_command sees it)."""
    import harness.ask as ask
    import harness.engines.concrete as concrete

    captured = {}

    class _FakeEngine:
        def dispatch(self, q, model, extra):
            captured.update(extra)
            return EngineResponse(
                success=True, text="ok", latency_ms=1, error=None,
                tokens_in=1, tokens_out=1, cost_usd=0.0,
            )

    monkeypatch.setattr(concrete, "get_engine", lambda name, **kw: _FakeEngine())
    ask._dispatch_one("claude-via-cc", "q", 0.30, 180, agentic=True)
    assert captured.get("agentic") is True


def test_agentic_present_in_ask_signatures():
    from harness.ask import _dispatch_one, run_panel, run_audit
    for fn in (_dispatch_one, run_panel, run_audit):
        assert "agentic" in inspect.signature(fn).parameters


def test_agentic_flag_in_cli():
    from harness.cli import ask_cmd
    assert "agentic" in [p.name for p in ask_cmd.params]
