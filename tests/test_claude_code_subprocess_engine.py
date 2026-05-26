"""W14-PATTERN-B-CLAUDE-CODE-SUBPROCESS: tests for the subprocess engine.

The actual ``claude`` CLI is NOT invoked by these tests — we mock
``subprocess.run`` to return canned JSON.  One smoke-test does a real
dispatch but is marked ``slow`` and excluded by default.

Coverage:
  - Helper functions (_resolve_binary, _resolve_mimo_tp_region,
    _engine_name_for_mimo_key) honor env vars + key prefix
  - MimoViaClaudeCodeEngine resolves region + endpoint from MIMO_REGION
  - _build_command sets --bare + --print + --output-format json + budget
  - _build_env sets ANTHROPIC_BASE_URL + AUTH_TOKEN + API_KEY
  - _build_env strips CLAUDE_CODE_USE_BEDROCK / VERTEX
  - dispatch parses success JSON into EngineResponse with provider cost
  - dispatch parses is_error JSON into failed EngineResponse with error_excerpt
  - dispatch handles subprocess timeout
  - dispatch handles binary-not-found (FileNotFoundError)
  - dispatch handles non-JSON stdout fallback
  - Factory: get_engine("mimo-via-claude") returns wired instance
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from harness.engines.base import EngineResponse
from harness.engines.claude_code_subprocess import (
    ClaudeCodeSubprocessEngine,
    DEFAULT_MODEL_PER_ENGINE,
    MimoViaClaudeCodeEngine,
    PROVIDER_ANTHROPIC_ENDPOINTS,
    _engine_name_for_mimo_key,
    _resolve_binary,
    _resolve_mimo_tp_region,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestResolveBinary:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HARNESS_CLAUDE_CODE_BINARY", raising=False)
        assert _resolve_binary() == "claude"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_CLAUDE_CODE_BINARY", "/custom/claude")
        assert _resolve_binary() == "/custom/claude"


class TestResolveMimoTpRegion:
    def test_default_sgp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MIMO_REGION", raising=False)
        assert _resolve_mimo_tp_region() == "mimo-tp-sgp"

    def test_explicit_sgp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIMO_REGION", "sgp")
        assert _resolve_mimo_tp_region() == "mimo-tp-sgp"

    def test_ams(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIMO_REGION", "ams")
        assert _resolve_mimo_tp_region() == "mimo-tp-ams"

    def test_cn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIMO_REGION", "cn")
        assert _resolve_mimo_tp_region() == "mimo-tp-cn"

    def test_unknown_falls_back_to_sgp(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MIMO_REGION", "narnia")
        assert _resolve_mimo_tp_region() == "mimo-tp-sgp"


class TestEngineNameForMimoKey:
    def test_tp_prefix_picks_regional_tp(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("MIMO_REGION", raising=False)
        assert _engine_name_for_mimo_key("tp-abc123") == "mimo-tp-sgp"

    def test_sk_prefix_picks_payg(self) -> None:
        assert _engine_name_for_mimo_key("sk-xyz789") == "mimo-payg"

    def test_other_prefix_picks_payg(self) -> None:
        assert _engine_name_for_mimo_key("random-key") == "mimo-payg"


# ---------------------------------------------------------------------------
# MimoViaClaudeCodeEngine constructor wiring
# ---------------------------------------------------------------------------


class TestMimoViaClaudeCodeEngine:
    def test_tp_key_routes_to_sgp_endpoint(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("MIMO_REGION", raising=False)
        eng = MimoViaClaudeCodeEngine(api_key="tp-test-abc")
        assert eng._base_url == (
            "https://token-plan-sgp.xiaomimimo.com/anthropic"
        )
        assert eng._default_model == "mimo-v2.5-pro"

    def test_sk_key_routes_to_payg_endpoint(self) -> None:
        eng = MimoViaClaudeCodeEngine(api_key="sk-test-xyz")
        assert eng._base_url == "https://api.xiaomimimo.com/anthropic"
        assert eng._default_model == "mimo-v2.5-pro"

    def test_region_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIMO_REGION", "ams")
        eng = MimoViaClaudeCodeEngine(api_key="tp-test-abc")
        assert eng._base_url == (
            "https://token-plan-ams.xiaomimimo.com/anthropic"
        )

    def test_engine_name(self) -> None:
        eng = MimoViaClaudeCodeEngine(api_key="tp-x")
        assert eng.name == "mimo-via-claude"


# ---------------------------------------------------------------------------
# _build_command + _build_env
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_includes_bare_print_json(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x",
            base_url="https://example.com/anthropic",
            default_model="mimo-v2.5-pro",
        )
        cmd = eng._build_command(model="", extra_args={})
        assert "--print" in cmd
        assert "--bare" in cmd
        assert "--output-format" in cmd
        # Find the value following --output-format
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "json"
        assert "--no-session-persistence" in cmd

    def test_model_resolution_uses_default(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="mimo-v2.5-pro",
        )
        cmd = eng._build_command(model="", extra_args={})
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "mimo-v2.5-pro"

    def test_model_override(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="default",
        )
        cmd = eng._build_command(
            model="qwen3.6-plus", extra_args={},
        )
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "qwen3.6-plus"

    def test_max_budget_default(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="d",
        )
        cmd = eng._build_command(model="m", extra_args={})
        idx = cmd.index("--max-budget-usd")
        # Default is 1.00
        assert float(cmd[idx + 1]) == pytest.approx(1.00)

    def test_max_budget_override(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="d",
        )
        cmd = eng._build_command(model="m", extra_args={"max_budget_usd": 0.05})
        idx = cmd.index("--max-budget-usd")
        assert float(cmd[idx + 1]) == pytest.approx(0.05)


class TestBuildEnv:
    def test_sets_anthropic_base_url(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x",
            base_url="https://mimo.example/anthropic",
            default_model="m",
        )
        env = eng._build_env()
        assert env["ANTHROPIC_BASE_URL"] == "https://mimo.example/anthropic"

    def test_sets_both_auth_envs(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-key-abc",
            base_url="https://x",
            default_model="m",
        )
        env = eng._build_env()
        assert env["ANTHROPIC_API_KEY"] == "tp-key-abc"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "tp-key-abc"

    def test_strips_bedrock_vertex_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="m",
        )
        env = eng._build_env()
        assert "CLAUDE_CODE_USE_BEDROCK" not in env
        assert "CLAUDE_CODE_USE_VERTEX" not in env

    def test_sets_claude_code_simple(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="m",
        )
        env = eng._build_env()
        assert env["CLAUDE_CODE_SIMPLE"] == "1"

    def test_empty_base_url_unsets_anthropic_base_url(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://stale.example")
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="", default_model="m",
        )
        env = eng._build_env()
        # Empty base_url means use Claude Code's built-in default
        assert "ANTHROPIC_BASE_URL" not in env


# ---------------------------------------------------------------------------
# dispatch (mocked subprocess)
# ---------------------------------------------------------------------------


def _make_subprocess_result(
    stdout: str = "", stderr: str = "", returncode: int = 0,
) -> MagicMock:
    """Build a CompletedProcess-shaped mock for subprocess.run."""
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


def _make_success_json(
    text: str = "OK",
    input_tokens: int = 1819,
    output_tokens: int = 28,
    cost: float = 0.01367,
) -> str:
    """Realistic Claude Code success JSON, mirroring the live probe."""
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "duration_ms": 9621,
        "result": text,
        "stop_reason": "end_turn",
        "session_id": "test-session-id",
        "total_cost_usd": cost,
        "usage": {
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": output_tokens,
        },
        "modelUsage": {
            "mimo-v2.5-pro": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "costUSD": cost,
            },
        },
        "uuid": "test-uuid",
    })


class TestDispatchMocked:
    def test_success_parses_response(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="m",
        )
        with patch(
            "harness.engines.claude_code_subprocess.subprocess.run",
            return_value=_make_subprocess_result(stdout=_make_success_json()),
        ):
            resp = eng.dispatch("test prompt", "m", {})
        assert resp.success is True
        assert resp.text == "OK"
        assert resp.tokens_in == 1819
        assert resp.tokens_out == 28
        assert resp.cost_usd == pytest.approx(0.01367)
        assert resp.error is None

    def test_is_error_subtype_parses_as_failure(self) -> None:
        err_json = json.dumps({
            "type": "result",
            "subtype": "error_max_budget_usd",
            "is_error": True,
            "result": "",
            "errors": ["Reached maximum budget ($0.01)"],
            "total_cost_usd": 0.2007,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="m",
        )
        with patch(
            "harness.engines.claude_code_subprocess.subprocess.run",
            return_value=_make_subprocess_result(stdout=err_json),
        ):
            resp = eng.dispatch("p", "m", {})
        assert resp.success is False
        assert "error_max_budget_usd" in (resp.error or "")
        assert "Reached maximum budget" in (resp.error or "")
        # Even on error, provider-reported cost is captured
        assert resp.cost_usd == pytest.approx(0.2007)

    def test_timeout_returns_error(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="m",
            timeout_s=5,
        )
        with patch(
            "harness.engines.claude_code_subprocess.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["claude"], timeout=5,
            ),
        ):
            resp = eng.dispatch("p", "m", {})
        assert resp.success is False
        assert "timeout" in (resp.error or "").lower()

    def test_binary_not_found_returns_error(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="m",
            binary="/nonexistent/claude",
        )
        with patch(
            "harness.engines.claude_code_subprocess.subprocess.run",
            side_effect=FileNotFoundError("No such file"),
        ):
            resp = eng.dispatch("p", "m", {})
        assert resp.success is False
        assert "claude binary not found" in (resp.error or "").lower() \
               or "not found" in (resp.error or "").lower()

    def test_non_json_stdout_with_zero_exit_treated_as_text(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="m",
        )
        with patch(
            "harness.engines.claude_code_subprocess.subprocess.run",
            return_value=_make_subprocess_result(
                stdout="plain text response", returncode=0,
            ),
        ):
            resp = eng.dispatch("p", "m", {})
        # No JSON, exit 0 → treat as raw text success
        assert resp.success is True
        assert resp.text == "plain text response"

    def test_empty_stdout_with_nonzero_exit_is_failure(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="tp-x", base_url="https://x", default_model="m",
        )
        with patch(
            "harness.engines.claude_code_subprocess.subprocess.run",
            return_value=_make_subprocess_result(
                stdout="", stderr="binary error", returncode=2,
            ),
        ):
            resp = eng.dispatch("p", "m", {})
        assert resp.success is False
        assert "binary error" in (resp.error or "") \
               or "exit" in (resp.error or "").lower()

    def test_missing_api_key_short_circuits(self) -> None:
        eng = ClaudeCodeSubprocessEngine(
            api_key="", base_url="https://x", default_model="m",
        )
        resp = eng.dispatch("p", "m", {})
        # No subprocess invoked — fails before
        assert resp.success is False
        assert "key" in (resp.error or "").lower()


# ---------------------------------------------------------------------------
# Factory integration
# ---------------------------------------------------------------------------


class TestFactoryIntegration:
    def test_get_engine_mimo_via_claude_returns_wired_instance(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Provide a fake MIMO_API_KEY so resolve_key succeeds
        monkeypatch.setenv("MIMO_API_KEY", "tp-test-key-from-fixture")
        # Defeat DPAPI lookup so the test isn't OS-dependent
        from harness.secrets import resolve as resolve_module
        monkeypatch.setattr(
            resolve_module, "resolve_key",
            lambda env_var, prefer_dpapi=True: "tp-test-key-from-fixture",
        )
        from harness.engines.concrete import get_engine
        eng = get_engine("mimo-via-claude")
        assert eng.name == "mimo-via-claude"
        # tp- key + default region (sgp) → sgp endpoint
        assert "token-plan-sgp.xiaomimimo.com" in eng._base_url

    def test_get_engine_mimo_via_claude_missing_key_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("MIMO_API_KEY", raising=False)
        from harness.secrets import resolve as resolve_module
        monkeypatch.setattr(
            resolve_module, "resolve_key",
            lambda env_var, prefer_dpapi=True: None,
        )
        from harness.engines.concrete import get_engine
        with pytest.raises(RuntimeError, match="mimo-via-claude"):
            get_engine("mimo-via-claude")


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_provider_endpoints_include_mimo_variants(self) -> None:
        # All four MiMo paths are mapped
        for key in ("mimo-tp-sgp", "mimo-tp-ams", "mimo-tp-cn", "mimo-payg"):
            assert key in PROVIDER_ANTHROPIC_ENDPOINTS
            assert PROVIDER_ANTHROPIC_ENDPOINTS[key].endswith("/anthropic")

    def test_provider_endpoints_include_kimi_via_cc(self) -> None:
        # Kimi path is mapped for future re-subscription
        assert "kimi-via-cc" in PROVIDER_ANTHROPIC_ENDPOINTS

    def test_default_models_per_engine(self) -> None:
        # Every endpoint has a default model
        for key in PROVIDER_ANTHROPIC_ENDPOINTS:
            assert key in DEFAULT_MODEL_PER_ENGINE
