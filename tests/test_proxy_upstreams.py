"""W14-PROXY-UPSTREAMS 2026-05-27: tests for the upstream registry."""
from __future__ import annotations

import pytest

from harness.proxy.upstreams import (
    DEFAULT_UPSTREAM_NAME,
    UpstreamSpec,
    get_upstream,
    list_upstreams,
)


class TestGetUpstream:
    def test_known_upstream_returns_spec(self) -> None:
        spec = get_upstream("kimi-http")
        assert isinstance(spec, UpstreamSpec)
        assert spec.name == "kimi-http"
        assert spec.transport == "http"
        assert spec.key_env == "KIMI_API_KEY"

    def test_unknown_upstream_raises_value_error(self) -> None:
        with pytest.raises(ValueError) as ctx:
            get_upstream("totally-made-up")
        msg = str(ctx.value)
        assert "totally-made-up" in msg
        # Error message lists valid names so the operator can recover
        assert "kimi-http" in msg

    def test_case_insensitive(self) -> None:
        assert get_upstream("KIMI-HTTP").name == "kimi-http"
        assert get_upstream("Mimo-Via-Claude-Code").name == "mimo-via-claude-code"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            get_upstream("")

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError):
            get_upstream(None)  # type: ignore[arg-type]


class TestUpstreamRegistry:
    def test_default_is_kimi_http(self) -> None:
        """Bare `harness proxy start` must keep landing on Kimi HTTP
        (pre-v0.5.1 behavior) until the operator opts into another."""
        assert DEFAULT_UPSTREAM_NAME == "kimi-http"
        spec = get_upstream(DEFAULT_UPSTREAM_NAME)
        assert spec.transport == "http"

    def test_list_returns_all_known(self) -> None:
        names = set(list_upstreams())
        # Snapshot the v0.5.1 set — any future addition is a deliberate
        # change, and any removal needs operator review (would break
        # someone's `harness proxy start --upstream X` invocation)
        assert names == {
            "kimi-http",
            "deepseek-http",
            "qwen-http",
            "mimo-via-claude-code",
            "kimi-via-claude-code",
        }

    def test_list_returns_snapshot_not_internal_state(self) -> None:
        """Mutating the returned dict must not affect future lookups."""
        listing = list_upstreams()
        listing["fake"] = None  # type: ignore[assignment]
        # Original still intact
        assert "fake" not in list_upstreams()


class TestPerUpstreamShape:
    def test_kimi_http(self) -> None:
        spec = get_upstream("kimi-http")
        assert spec.transport == "http"
        assert spec.base_url.startswith("https://api.moonshot.cn")
        assert "chat/completions" in spec.base_url

    def test_deepseek_http(self) -> None:
        spec = get_upstream("deepseek-http")
        assert spec.transport == "http"
        assert spec.key_env == "DEEPSEEK_API_KEY"
        assert "api.deepseek.com" in spec.base_url

    def test_qwen_http(self) -> None:
        spec = get_upstream("qwen-http")
        assert spec.transport == "http"
        assert spec.key_env == "DASHSCOPE_API_KEY"
        assert "dashscope.aliyuncs.com" in spec.base_url

    def test_mimo_via_claude_code(self) -> None:
        spec = get_upstream("mimo-via-claude-code")
        assert spec.transport == "claude-code-subprocess"
        assert spec.key_env == "MIMO_API_KEY"
        assert "xiaomimimo.com" in spec.base_url
        # Token Plan UA-gating note must surface — this is the
        # justification for routing through subprocess
        assert "UA" in spec.tos_notes or "User-Agent" in spec.tos_notes
        # Subprocess upstreams need env overrides
        assert spec.env_overrides
        assert (
            spec.env_overrides.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
            == "mimo-v2.5-pro"
        )

    def test_kimi_via_claude_code(self) -> None:
        spec = get_upstream("kimi-via-claude-code")
        assert spec.transport == "claude-code-subprocess"
        assert spec.key_env == "KIMI_API_KEY"
        assert "kimi.com" in spec.base_url
        assert spec.env_overrides

    def test_subprocess_upstreams_inherit_anthropic_base_url(self) -> None:
        """The subprocess upstream's `base_url` IS what we set as
        ANTHROPIC_BASE_URL on the child process — make that contract
        explicit so any future refactor that breaks it gets caught."""
        for name in ("mimo-via-claude-code", "kimi-via-claude-code"):
            spec = get_upstream(name)
            # base_url should look like an Anthropic-protocol root,
            # not a /chat/completions endpoint
            assert "/chat/completions" not in spec.base_url, (
                f"{name}: base_url must be the protocol root, not the "
                f"OpenAI chat endpoint — got {spec.base_url}"
            )


class TestUpstreamSpecFrozen:
    """UpstreamSpec is a frozen dataclass — mutation must raise."""

    def test_frozen(self) -> None:
        spec = get_upstream("kimi-http")
        with pytest.raises(Exception):
            spec.name = "x"  # type: ignore[misc]
