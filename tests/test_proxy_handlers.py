"""W14-PROXY-UPSTREAMS 2026-05-27: tests for proxy/handlers.py
(HTTP + Claude-Code-subprocess transports)."""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from harness.proxy.handlers import (
    claude_code_subprocess_handler,
    claude_json_to_openai_response,
    dispatch_to_upstream,
    http_handler,
    messages_to_prompts,
    run_claude_subprocess,
    _build_subprocess_env,
    _extract_text,
)
from harness.proxy.upstreams import get_upstream


# ---------------------------------------------------------------------------
# Text / message helpers
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_string_passthrough(self) -> None:
        assert _extract_text("hello") == "hello"

    def test_list_of_text_parts(self) -> None:
        parts = [
            {"type": "text", "text": "hello "},
            {"type": "text", "text": "world"},
        ]
        assert _extract_text(parts) == "hello world"

    def test_list_skips_non_text_parts(self) -> None:
        parts = [
            {"type": "text", "text": "keep"},
            {"type": "image", "url": "..."},
            {"type": "text", "text": " me"},
        ]
        assert _extract_text(parts) == "keep me"

    def test_none(self) -> None:
        assert _extract_text(None) == ""

    def test_unknown_object_str_fallback(self) -> None:
        assert _extract_text(42) == "42"


class TestMessagesToPrompts:
    def test_single_user_no_assistant_sends_verbatim(self) -> None:
        # The shim's special-case: a lone user message goes through
        # without "User:" prefix, so single-shot prompts feel natural
        system, user_text = messages_to_prompts([
            {"role": "user", "content": "What is 2 + 2?"},
        ])
        assert system == ""
        assert user_text == "What is 2 + 2?"

    def test_system_plus_user(self) -> None:
        system, user_text = messages_to_prompts([
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Hi"},
        ])
        assert "concise" in system
        assert user_text == "Hi"

    def test_multi_turn_uses_role_prefixes(self) -> None:
        system, user_text = messages_to_prompts([
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ])
        assert system == ""
        assert "User: Q1" in user_text
        assert "Assistant: A1" in user_text
        assert "User: Q2" in user_text

    def test_list_content_format(self) -> None:
        system, user_text = messages_to_prompts([
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Tell me "},
                    {"type": "text", "text": "a joke"},
                ],
            },
        ])
        assert user_text == "Tell me a joke"

    def test_multiple_system_messages_concatenated(self) -> None:
        system, _ = messages_to_prompts([
            {"role": "system", "content": "Rule 1: be brief."},
            {"role": "system", "content": "Rule 2: be honest."},
            {"role": "user", "content": "Hi"},
        ])
        assert "Rule 1" in system
        assert "Rule 2" in system


# ---------------------------------------------------------------------------
# Subprocess env construction
# ---------------------------------------------------------------------------


class TestBuildSubprocessEnv:
    def test_sets_anthropic_base_url_and_keys(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        env = _build_subprocess_env(spec, "tp-abc123")
        assert env["ANTHROPIC_BASE_URL"] == spec.base_url
        assert env["ANTHROPIC_AUTH_TOKEN"] == "tp-abc123"
        assert env["ANTHROPIC_API_KEY"] == "tp-abc123"
        assert env["ANTHROPIC_MODEL"] == "mimo-v2.5-pro"

    def test_applies_env_overrides(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        env = _build_subprocess_env(spec, "tp-abc123")
        # The MiMo spec pins all three model-default env vars
        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "mimo-v2.5-pro"
        assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "mimo-v2.5-pro"
        assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "mimo-v2.5-pro"
        assert env["ENABLE_TOOL_SEARCH"] == "false"

    def test_inherits_parent_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_TEST_INHERIT_ME", "yes")
        spec = get_upstream("mimo-via-claude-code")
        env = _build_subprocess_env(spec, "tp-x")
        assert env.get("HARNESS_TEST_INHERIT_ME") == "yes"


# ---------------------------------------------------------------------------
# Claude --bare invocation (mocked subprocess)
# ---------------------------------------------------------------------------


def _fake_completed_proc(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> SimpleNamespace:
    """Build a fake subprocess.CompletedProcess-like object for the
    _run= test seam."""
    return SimpleNamespace(
        returncode=returncode, stdout=stdout, stderr=stderr,
    )


class TestRunClaudeSubprocess:
    def test_happy_path_parses_json(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        canned = json.dumps({
            "result": "Hello world",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
        })
        fake_run = MagicMock(return_value=_fake_completed_proc(
            returncode=0, stdout=canned,
        ))
        result = run_claude_subprocess(
            spec, system="", user_text="hi",
            api_key="tp-x", claude_binary="/fake/claude",
            _run=fake_run,
        )
        assert result["result"] == "Hello world"
        # Was called with --bare + --print + --output-format json
        cmd = fake_run.call_args.args[0]
        assert "--bare" in cmd
        assert "--print" in cmd
        assert "json" in cmd

    def test_extracts_json_from_noisy_stdout(self) -> None:
        """Claude sometimes emits warnings before the JSON; the parser
        finds the first ``{`` and decodes from there."""
        spec = get_upstream("mimo-via-claude-code")
        noisy = (
            "(node:1234) some warning\n"
            "claude-code v1.x\n"
            '{"result": "ok", "usage": {}, "stop_reason": "end_turn"}'
        )
        fake_run = MagicMock(return_value=_fake_completed_proc(
            returncode=0, stdout=noisy,
        ))
        result = run_claude_subprocess(
            spec, system="", user_text="hi",
            api_key="tp-x", claude_binary="/fake/claude",
            _run=fake_run,
        )
        assert result["result"] == "ok"

    def test_nonzero_exit_raises_runtime_error(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        fake_run = MagicMock(return_value=_fake_completed_proc(
            returncode=1, stdout="", stderr="claude failed: 401",
        ))
        with pytest.raises(RuntimeError) as ctx:
            run_claude_subprocess(
                spec, system="", user_text="hi",
                api_key="tp-x", claude_binary="/fake/claude",
                _run=fake_run,
            )
        assert "exit 1" in str(ctx.value)
        assert "401" in str(ctx.value)

    def test_no_json_raises_runtime_error(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        fake_run = MagicMock(return_value=_fake_completed_proc(
            returncode=0, stdout="just plain text, no braces here",
        ))
        with pytest.raises(RuntimeError) as ctx:
            run_claude_subprocess(
                spec, system="", user_text="hi",
                api_key="tp-x", claude_binary="/fake/claude",
                _run=fake_run,
            )
        assert "no JSON" in str(ctx.value)

    def test_is_error_flag_raises_runtime_error(self) -> None:
        """Claude can return exit 0 + JSON with is_error=true."""
        spec = get_upstream("mimo-via-claude-code")
        canned = json.dumps({
            "is_error": True,
            "error": "rate limit",
            "result": "",
        })
        fake_run = MagicMock(return_value=_fake_completed_proc(
            returncode=0, stdout=canned,
        ))
        with pytest.raises(RuntimeError) as ctx:
            run_claude_subprocess(
                spec, system="", user_text="hi",
                api_key="tp-x", claude_binary="/fake/claude",
                _run=fake_run,
            )
        assert "rate limit" in str(ctx.value)

    def test_invalid_json_raises_json_decode_error(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        fake_run = MagicMock(return_value=_fake_completed_proc(
            returncode=0, stdout="{not valid json",
        ))
        with pytest.raises(json.JSONDecodeError):
            run_claude_subprocess(
                spec, system="", user_text="hi",
                api_key="tp-x", claude_binary="/fake/claude",
                _run=fake_run,
            )


# ---------------------------------------------------------------------------
# Claude JSON → OpenAI shape translation
# ---------------------------------------------------------------------------


class TestClaudeJsonToOpenAiResponse:
    def test_basic_shape(self) -> None:
        claude = {
            "result": "Hi!",
            "usage": {"input_tokens": 7, "output_tokens": 3},
            "stop_reason": "end_turn",
        }
        out = claude_json_to_openai_response(claude, model="mimo-v2.5-pro")
        assert out["object"] == "chat.completion"
        assert out["model"] == "mimo-v2.5-pro"
        assert out["choices"][0]["message"]["role"] == "assistant"
        assert out["choices"][0]["message"]["content"] == "Hi!"
        assert out["choices"][0]["finish_reason"] == "stop"

    def test_usage_mapping(self) -> None:
        claude = {
            "result": "x",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "stop_reason": "end_turn",
        }
        out = claude_json_to_openai_response(claude, model="m")
        assert out["usage"] == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }

    def test_stop_reason_mapping(self) -> None:
        mappings = {
            "end_turn": "stop",
            "stop_sequence": "stop",
            "max_tokens": "length",
            "tool_use": "tool_calls",
            "unknown_reason": "stop",  # fallback
        }
        for claude_reason, openai_reason in mappings.items():
            claude = {
                "result": "",
                "usage": {},
                "stop_reason": claude_reason,
            }
            out = claude_json_to_openai_response(claude, model="m")
            assert out["choices"][0]["finish_reason"] == openai_reason, (
                f"{claude_reason!r} → expected {openai_reason!r}"
            )

    def test_empty_usage_safe(self) -> None:
        claude = {"result": "x", "stop_reason": "end_turn"}
        out = claude_json_to_openai_response(claude, model="m")
        # Missing usage → zeros, not crash
        assert out["usage"]["prompt_tokens"] == 0
        assert out["usage"]["completion_tokens"] == 0
        assert out["usage"]["total_tokens"] == 0

    def test_unique_id_per_call(self) -> None:
        claude = {"result": "", "usage": {}, "stop_reason": "end_turn"}
        a = claude_json_to_openai_response(claude, model="m")
        b = claude_json_to_openai_response(claude, model="m")
        # Random uuid in the id field — both should start with chatcmpl-
        assert a["id"].startswith("chatcmpl-")
        assert b["id"].startswith("chatcmpl-")
        assert a["id"] != b["id"]


# ---------------------------------------------------------------------------
# Subprocess handler end-to-end (async)
# ---------------------------------------------------------------------------


class TestSubprocessHandler:
    @pytest.mark.asyncio
    async def test_invalid_json_body_returns_400(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        body, status = await claude_code_subprocess_handler(
            spec, b"not json at all", "tp-x",
        )
        assert status == 400
        assert b"invalid JSON" in body

    @pytest.mark.asyncio
    async def test_missing_messages_returns_400(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        body, status = await claude_code_subprocess_handler(
            spec, b'{"model": "x"}', "tp-x",
        )
        assert status == 400
        assert b"messages" in body

    @pytest.mark.asyncio
    async def test_empty_messages_returns_400(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        body, status = await claude_code_subprocess_handler(
            spec, b'{"messages": []}', "tp-x",
        )
        assert status == 400

    @pytest.mark.asyncio
    async def test_messages_with_only_system_returns_400(self) -> None:
        """System-only messages produce empty user_text — must error."""
        spec = get_upstream("mimo-via-claude-code")
        body, status = await claude_code_subprocess_handler(
            spec, b'{"messages": [{"role": "system", "content": "x"}]}',
            "tp-x",
        )
        assert status == 400
        assert b"user" in body

    @pytest.mark.asyncio
    async def test_happy_path_returns_openai_shape(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spec = get_upstream("mimo-via-claude-code")
        canned = json.dumps({
            "result": "Hello world",
            "usage": {"input_tokens": 5, "output_tokens": 2},
            "stop_reason": "end_turn",
        })
        # Inject a fake subprocess runner that returns the canned JSON
        fake_run = MagicMock(return_value=_fake_completed_proc(
            returncode=0, stdout=canned,
        ))
        request = json.dumps({
            "model": "mimo-v2.5-pro",
            "messages": [{"role": "user", "content": "hi"}],
        }).encode()
        body, status = await claude_code_subprocess_handler(
            spec, request, "tp-x",
            _runner=fake_run,
        )
        assert status == 200
        parsed = json.loads(body)
        assert parsed["object"] == "chat.completion"
        assert parsed["choices"][0]["message"]["content"] == "Hello world"

    @pytest.mark.asyncio
    async def test_subprocess_runtime_error_returns_502(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        fake_run = MagicMock(return_value=_fake_completed_proc(
            returncode=1, stdout="", stderr="401",
        ))
        request = json.dumps({
            "messages": [{"role": "user", "content": "hi"}],
        }).encode()
        body, status = await claude_code_subprocess_handler(
            spec, request, "tp-x",
            _runner=fake_run,
        )
        assert status == 502
        assert b"upstream" in body.lower() or b"RuntimeError" in body


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestDispatchToUpstream:
    @pytest.mark.asyncio
    async def test_routes_to_http_handler_for_http_transport(self) -> None:
        spec = get_upstream("kimi-http")

        class _FakeClient:
            def __init__(self):
                self.url = None

            async def post(self, url, **kwargs):
                self.url = url
                return SimpleNamespace(content=b"{}", status_code=200)

        client = _FakeClient()
        body, status = await dispatch_to_upstream(
            spec, b'{}', "sk-key", client,
        )
        assert status == 200
        assert client.url == spec.base_url

    @pytest.mark.asyncio
    async def test_routes_to_subprocess_handler_for_subprocess(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        body, status = await dispatch_to_upstream(
            spec, b'not json', "tp-x", http_client=None,
        )
        # Subprocess handler returns 400 for invalid JSON without
        # spawning a real subprocess
        assert status == 400

    @pytest.mark.asyncio
    async def test_unknown_transport_raises(self) -> None:
        from dataclasses import replace
        spec = replace(get_upstream("kimi-http"), transport="weird")
        with pytest.raises(ValueError) as ctx:
            await dispatch_to_upstream(spec, b'{}', "x", None)
        assert "weird" in str(ctx.value)
