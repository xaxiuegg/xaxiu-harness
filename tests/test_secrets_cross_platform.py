"""W11-DPAPI-CROSS-PLATFORM: tests for the .env-first cross-platform
secret resolver.

The harness routes through harness.secrets.resolve.resolve_key() which
implements precedence: os.environ > .env file > DPAPI (Windows only,
gracefully skipped elsewhere).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from harness.secrets import env_file, resolve


# -- env_file parser ------------------------------------------------------


def test_read_env_file_missing_returns_empty_dict(tmp_path):
    result = env_file.read_env_file(tmp_path / "no-such.env")
    assert result == {}


def test_read_env_file_basic(tmp_path):
    p = tmp_path / ".env"
    p.write_text("KIMI_API_KEY=ms-real-value\nDEEPSEEK_API_KEY=deepseek-x\n",
                 encoding="utf-8")
    out = env_file.read_env_file(p)
    assert out["KIMI_API_KEY"] == "ms-real-value"
    assert out["DEEPSEEK_API_KEY"] == "deepseek-x"


def test_read_env_file_skips_comments_and_blanks(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# top comment\n"
        "\n"
        "KIMI_API_KEY=val1\n"
        "# inline comment block\n"
        "DEEPSEEK_API_KEY=val2\n",
        encoding="utf-8",
    )
    out = env_file.read_env_file(p)
    assert out == {"KIMI_API_KEY": "val1", "DEEPSEEK_API_KEY": "val2"}


def test_read_env_file_handles_quoted_values(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        'KIMI_API_KEY="value with spaces"\n'
        "DEEPSEEK_API_KEY='single quoted'\n"
        "MIMO_API_KEY=unquoted-value\n",
        encoding="utf-8",
    )
    out = env_file.read_env_file(p)
    assert out["KIMI_API_KEY"] == "value with spaces"
    assert out["DEEPSEEK_API_KEY"] == "single quoted"
    assert out["MIMO_API_KEY"] == "unquoted-value"


def test_read_env_file_silently_skips_malformed_lines(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "VALID_KEY=ok\n"
        "this line has no equals sign\n"
        "ANOTHER_KEY=ok2\n",
        encoding="utf-8",
    )
    out = env_file.read_env_file(p)
    assert out == {"VALID_KEY": "ok", "ANOTHER_KEY": "ok2"}


def test_read_env_file_strips_export_prefix(tmp_path):
    p = tmp_path / ".env"
    p.write_text("export KIMI_API_KEY=value-here\n", encoding="utf-8")
    out = env_file.read_env_file(p)
    assert out["KIMI_API_KEY"] == "value-here"


def test_get_key_treats_empty_as_missing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("KIMI_API_KEY=\n", encoding="utf-8")
    # Template default: operator left it blank
    assert env_file.get_key("KIMI_API_KEY", p) is None


# -- write_key idempotency -----------------------------------------------


def test_write_key_creates_file_if_missing(tmp_path):
    p = tmp_path / "subdir" / ".env"
    env_file.write_key("KIMI_API_KEY", "value-x", p)
    assert p.exists()
    assert env_file.get_key("KIMI_API_KEY", p) == "value-x"


def test_write_key_replaces_existing_value(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# my comment\n"
        "KIMI_API_KEY=old\n"
        "DEEPSEEK_API_KEY=keep\n",
        encoding="utf-8",
    )
    env_file.write_key("KIMI_API_KEY", "new-value", p)
    out = env_file.read_env_file(p)
    assert out["KIMI_API_KEY"] == "new-value"
    assert out["DEEPSEEK_API_KEY"] == "keep"  # unrelated key untouched
    # Comment preserved
    assert "# my comment" in p.read_text(encoding="utf-8")


def test_write_key_appends_when_key_missing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# existing\nDEEPSEEK_API_KEY=val\n", encoding="utf-8")
    env_file.write_key("KIMI_API_KEY", "new-val", p)
    out = env_file.read_env_file(p)
    assert out == {"DEEPSEEK_API_KEY": "val", "KIMI_API_KEY": "new-val"}


# -- resolve_key precedence ----------------------------------------------


def test_resolve_key_prefers_os_environ(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("KIMI_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("KIMI_API_KEY", "from-os-env")
    val = resolve.resolve_key("KIMI_API_KEY", env_file_path=p)
    assert val == "from-os-env"


def test_resolve_key_falls_back_to_dotenv(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("KIMI_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    val = resolve.resolve_key("KIMI_API_KEY", env_file_path=p)
    assert val == "from-dotenv"


def test_resolve_key_returns_none_when_nowhere(tmp_path, monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    val = resolve.resolve_key(
        "KIMI_API_KEY",
        env_file_path=tmp_path / "missing.env",
    )
    assert val is None


def test_resolve_key_skips_empty_dotenv_value(tmp_path, monkeypatch):
    """Template-default empty values don't count as 'set'."""
    p = tmp_path / ".env"
    p.write_text("KIMI_API_KEY=\n", encoding="utf-8")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    val = resolve.resolve_key("KIMI_API_KEY", env_file_path=p)
    assert val is None


def test_resolve_key_handles_dpapi_unavailable_on_non_windows(tmp_path, monkeypatch):
    """Critical W11 contract: agents running on Linux/Mac don't crash
    when DPAPI is unavailable.  resolve_key falls through silently."""
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    # No env, no .env file, DPAPI unavailable -> None (not raise)
    val = resolve.resolve_key(
        "KIMI_API_KEY",
        env_file_path=tmp_path / "missing.env",
    )
    assert val is None


def test_resolve_key_prefer_dpapi_checks_dpapi_before_dotenv(tmp_path, monkeypatch):
    """Legacy Windows operator flow: prefer_dpapi=True preserves
    pre-W11 DPAPI-first behavior."""
    p = tmp_path / ".env"
    p.write_text("KIMI_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    # Stub DPAPI to claim it has the key with a different value
    monkeypatch.setattr(sys, "platform", "win32")

    class _FakeDpapi:
        @staticmethod
        def has_secret(name): return name == "KIMI_API_KEY"
        @staticmethod
        def decrypt_secret(name): return "from-dpapi"

    monkeypatch.setattr("harness.secrets.resolve._try_dpapi",
                         lambda name: "from-dpapi" if name == "KIMI_API_KEY" else None)
    val = resolve.resolve_key(
        "KIMI_API_KEY", env_file_path=p, prefer_dpapi=True,
    )
    assert val == "from-dpapi"  # DPAPI wins over .env when prefer_dpapi


# -- source_of for the env UI ---------------------------------------------


def test_source_of_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "x")
    assert resolve.source_of(
        "KIMI_API_KEY", env_file_path=tmp_path / "missing.env",
    ) == "env"


def test_source_of_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("KIMI_API_KEY=val\n", encoding="utf-8")
    assert resolve.source_of("KIMI_API_KEY", env_file_path=p) == "dotenv"


def test_source_of_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    assert resolve.source_of(
        "KIMI_API_KEY", env_file_path=tmp_path / "missing.env",
    ) == "missing"


def test_is_set_truthy_when_resolvable(tmp_path, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "x")
    assert resolve.is_set("KIMI_API_KEY")


def test_is_set_falsey_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    assert not resolve.is_set(
        "KIMI_API_KEY", env_file_path=tmp_path / "missing.env",
    )


# -- default_env_path discovery ------------------------------------------


def test_default_env_path_finds_adjacent_harness_dir(tmp_path):
    """Walks up looking for .harness/ + .env in same dir."""
    project = tmp_path / "deep" / "nested" / "project"
    project.mkdir(parents=True)
    (project / ".harness").mkdir()
    (project / ".env").write_text("KIMI_API_KEY=x\n", encoding="utf-8")
    # Starting from project subdir, default_env_path finds it
    sub = project / "src" / "foo"
    sub.mkdir(parents=True)
    result = resolve.default_env_path(start=sub)
    assert result == project / ".env"


def test_default_env_path_falls_back_when_no_harness_dir(tmp_path):
    sub = tmp_path / "empty"
    sub.mkdir()
    result = resolve.default_env_path(start=sub)
    # No .harness/ found upward; falls back to start/.env
    assert result == sub / ".env"


# -- Integration: engine init uses cross-platform resolver -----------------


def test_engine_get_engine_reads_dotenv_when_env_missing(tmp_path, monkeypatch):
    """End-to-end: get_engine() picks up a .env file value on any platform."""
    from harness.engines import concrete

    # Stub the engine class so we don't need a real API
    class _FakeEngine:
        def __init__(self, api_key, **kw): self.api_key = api_key

    monkeypatch.setattr(concrete, "DeepSeekConcrete", _FakeEngine)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    # Point default_env_path at our tmp .env via monkeypatch
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=test-from-dotenv\n",
                         encoding="utf-8")
    monkeypatch.setattr(
        "harness.secrets.resolve.default_env_path",
        lambda start=None: env_path,
    )

    eng = concrete.get_engine("deepseek", prefer_dpapi=False)
    assert eng.api_key == "test-from-dotenv"
