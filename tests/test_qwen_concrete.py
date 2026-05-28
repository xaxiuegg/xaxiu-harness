"""W14-KIMI-REPLACEMENT-WITH-QWEN 2026-05-28: tests for QwenConcrete
(Tier 1D scaffold).

Live validation is gated on the operator acquiring DASHSCOPE_API_KEY;
these tests mock httpx so the adapter shape + response parsing are
verified without requiring the key.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from harness.engines.base import EngineResponse
from harness.engines.concrete import QwenConcrete, get_engine


@pytest.fixture
def fake_dashscope_response() -> MagicMock:
    """A mocked httpx response shaped like a real DashScope reply."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "qwen-plus",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from Qwen"},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    return resp


class TestQwenConcrete:
    def test_dispatch_returns_engine_response(
        self, fake_dashscope_response: MagicMock,
    ) -> None:
        engine = QwenConcrete(api_key="sk-fake-dashscope-key")
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                fake_dashscope_response
            )
            response = engine.dispatch("Hello", "qwen-plus")
        assert isinstance(response, EngineResponse)
        assert response.success is True
        assert response.text == "Hello from Qwen"

    def test_default_model_is_qwen_plus(
        self, fake_dashscope_response: MagicMock,
    ) -> None:
        """Empty / 'auto' / 'qwen' / 'default' model arg → qwen-plus."""
        engine = QwenConcrete(api_key="sk-fake")
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = fake_dashscope_response
            engine.dispatch("Hello", "")
            payload = mock_post.call_args.kwargs.get("json")
            assert payload["model"] == "qwen-plus"

    def test_dispatch_hits_dashscope_endpoint(
        self, fake_dashscope_response: MagicMock,
    ) -> None:
        engine = QwenConcrete(api_key="sk-fake")
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = fake_dashscope_response
            engine.dispatch("Hello", "qwen-plus")
            call_args = mock_post.call_args
            url = call_args.args[0]
            assert url == (
                "https://dashscope.aliyuncs.com/compatible-mode/"
                "v1/chat/completions"
            )

    def test_authorization_header_includes_api_key(
        self, fake_dashscope_response: MagicMock,
    ) -> None:
        engine = QwenConcrete(api_key="sk-my-secret-dashscope-key")
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = fake_dashscope_response
            engine.dispatch("Hello", "qwen-plus")
            headers = mock_post.call_args.kwargs.get("headers", {})
            assert headers.get("Authorization") == "Bearer sk-my-secret-dashscope-key"
            assert headers.get("Content-Type") == "application/json"

    def test_payload_has_openai_shape(
        self, fake_dashscope_response: MagicMock,
    ) -> None:
        engine = QwenConcrete(api_key="sk-fake")
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = fake_dashscope_response
            engine.dispatch("My prompt", "qwen-plus")
            payload = mock_post.call_args.kwargs.get("json")
            assert payload["model"] == "qwen-plus"
            assert payload["messages"] == [
                {"role": "user", "content": "My prompt"},
            ]
            # Default tunables
            assert payload["temperature"] == 0.7
            assert payload["max_tokens"] == 8192

    def test_extra_args_override_temperature_and_max_tokens(
        self, fake_dashscope_response: MagicMock,
    ) -> None:
        engine = QwenConcrete(api_key="sk-fake")
        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = fake_dashscope_response
            engine.dispatch(
                "Hello", "qwen-plus",
                extra_args={"temperature": 0.2, "max_tokens": 1024},
            )
            payload = mock_post.call_args.kwargs.get("json")
            assert payload["temperature"] == 0.2
            assert payload["max_tokens"] == 1024

    def test_tokens_in_out_extracted_from_usage(
        self, fake_dashscope_response: MagicMock,
    ) -> None:
        engine = QwenConcrete(api_key="sk-fake")
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                fake_dashscope_response
            )
            response = engine.dispatch("Hello", "qwen-plus")
        assert response.tokens_in == 10
        assert response.tokens_out == 5


class TestQwenInFactory:
    def test_get_engine_qwen_returns_qwen_concrete(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`get_engine('qwen')` returns a QwenConcrete instance + uses
        DASHSCOPE_API_KEY.

        Patches the resolver directly to avoid test-ordering pollution
        from .env files or other tests that may set DPAPI-routed keys.
        """
        with patch(
            "harness.secrets.resolve.resolve_key",
            return_value="sk-test-dashscope",
        ):
            engine = get_engine("qwen", prefer_dpapi=False)
        # Compare by class name rather than isinstance to avoid module-
        # reload identity mismatches when other tests reload the module
        assert type(engine).__name__ == "QwenConcrete"
        assert "qwen" in type(engine).__module__.lower() or \
               "concrete" in type(engine).__module__.lower()

    def test_get_engine_qwen_raises_without_key(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing DASHSCOPE_API_KEY → RuntimeError (NOT silent ok)."""
        with patch(
            "harness.secrets.resolve.resolve_key",
            return_value="",
        ):
            with pytest.raises(RuntimeError) as ctx:
                get_engine("qwen", prefer_dpapi=False)
        assert "qwen" in str(ctx.value).lower()


class TestQwenInBackendList:
    def test_qwen_in_supported_backends(self) -> None:
        """SUPPORTED_BACKENDS must include qwen so doctor + various
        admin verbs treat it as a first-class engine."""
        from harness._constants import SUPPORTED_BACKENDS
        assert "qwen" in SUPPORTED_BACKENDS

    def test_qwen_env_var_registered(self) -> None:
        from harness._constants import API_KEY_ENV_VARS
        assert "qwen" in API_KEY_ENV_VARS
        assert API_KEY_ENV_VARS["qwen"] == "DASHSCOPE_API_KEY"


class TestQwenInBudgetPricing:
    def test_qwen_pricing_registered(self) -> None:
        """W14-KIMI-REPLACEMENT-WITH-QWEN: budget module must price
        qwen dispatches.  Without an entry, cost_known=False would tag
        every qwen call as unpriced."""
        from harness.budget import PRICING_USD_PER_M_TOKENS
        assert "qwen" in PRICING_USD_PER_M_TOKENS
        # Per strategic plan: ~$0.97/M blended.  qwen-plus default is
        # $0.40 input / $1.20 output → matches.
        assert PRICING_USD_PER_M_TOKENS["qwen"]["input"] > 0
        assert PRICING_USD_PER_M_TOKENS["qwen"]["output"] > 0
