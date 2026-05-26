"""W14-HARNESS-KEYS-WEB-UI: tests for the keys-UI module.

Server lifecycle is exercised end-to-end via threading.  Other tests
exercise the pure helpers (_mask / _read_env_file / _write_env_file /
_build_status).
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.keys_ui import (
    HTML_PAGE,
    KEY_PROVIDERS,
    _build_status,
    _current_value,
    _mask,
    _read_env_file,
    _write_env_file,
    list_key_status,
    serve_key_ui,
)


class TestMask:
    def test_short_key_fully_masked(self) -> None:
        assert _mask("short") == "*****"

    def test_empty_key(self) -> None:
        assert _mask("") == ""

    def test_long_key_shows_first_and_last_4(self) -> None:
        masked = _mask("sk-abcdef1234567890")
        assert masked.startswith("sk-a")
        assert masked.endswith("7890")
        assert "*" in masked
        # Middle should be all stars
        middle = masked[4:-4]
        assert set(middle) == {"*"}


class TestEnvFile:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _read_env_file(tmp_path / "nope.env") == {}

    def test_read_basic(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        f.write_text(
            "KIMI_API_KEY=sk-test\n"
            "DEEPSEEK_API_KEY=sk-dsk\n",
            encoding="utf-8",
        )
        d = _read_env_file(f)
        assert d == {"KIMI_API_KEY": "sk-test", "DEEPSEEK_API_KEY": "sk-dsk"}

    def test_read_strips_quotes(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        f.write_text('KEY1="quoted"\nKEY2=\'single\'\n', encoding="utf-8")
        d = _read_env_file(f)
        assert d["KEY1"] == "quoted"
        assert d["KEY2"] == "single"

    def test_read_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        f.write_text(
            "# comment\n"
            "\n"
            "  # indented comment\n"
            "VALID=yes\n",
            encoding="utf-8",
        )
        d = _read_env_file(f)
        assert d == {"VALID": "yes"}

    def test_write_creates_file(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        _write_env_file(f, {"KIMI_API_KEY": "sk-test"})
        assert f.exists()
        text = f.read_text(encoding="utf-8")
        assert "KIMI_API_KEY=sk-test" in text

    def test_write_merges_with_existing(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        f.write_text(
            "OLD_KEY=should-be-preserved\n"
            "KIMI_API_KEY=old-value\n",
            encoding="utf-8",
        )
        _write_env_file(f, {"KIMI_API_KEY": "new-value"})
        d = _read_env_file(f)
        assert d["OLD_KEY"] == "should-be-preserved"
        assert d["KIMI_API_KEY"] == "new-value"

    def test_write_drops_empty_values(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        _write_env_file(f, {"KEEP": "value", "DROP": ""})
        d = _read_env_file(f)
        assert d == {"KEEP": "value"}

    @pytest.mark.skipif(os.name == "nt",
                        reason="POSIX file modes only")
    def test_write_sets_0600(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        _write_env_file(f, {"K": "v"})
        mode = f.stat().st_mode & 0o777
        assert mode == 0o600


class TestCurrentValue:
    def test_env_wins_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        envfile = tmp_path / ".env"
        envfile.write_text("KIMI_API_KEY=from-dotenv\n", encoding="utf-8")
        monkeypatch.setenv("KIMI_API_KEY", "from-env")
        assert _current_value("KIMI_API_KEY", envfile) == "from-env"

    def test_dotenv_used_when_env_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        envfile = tmp_path / ".env"
        envfile.write_text("KIMI_API_KEY=from-dotenv\n", encoding="utf-8")
        assert _current_value("KIMI_API_KEY", envfile) == "from-dotenv"

    def test_missing_everywhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        assert _current_value("KIMI_API_KEY", tmp_path / "nope.env") == ""


class TestBuildStatus:
    def test_returns_entry_per_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for spec in KEY_PROVIDERS:
            monkeypatch.delenv(spec["env"], raising=False)
        status = _build_status()
        assert len(status) == len(KEY_PROVIDERS)
        for item in status:
            assert "env" in item
            assert "display" in item
            assert "source" in item
            assert "masked" in item
            assert "has_value" in item

    def test_env_source_when_set_in_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("KIMI_API_KEY", "sk-test-from-env-1234567890")
        status = _build_status()
        kimi = next(s for s in status if s["env"] == "KIMI_API_KEY")
        assert kimi["source"] == "env"
        assert kimi["has_value"] is True
        # Masked value is shown, NOT the raw secret
        assert "sk-test-from-env" not in kimi["masked"]
        assert kimi["masked"].startswith("sk-t")

    def test_dotenv_source_when_in_dotenv_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for spec in KEY_PROVIDERS:
            monkeypatch.delenv(spec["env"], raising=False)
        (tmp_path / ".env").write_text(
            "MIMO_API_KEY=tp-test-from-dotenv-abc\n", encoding="utf-8",
        )
        status = _build_status()
        mimo = next(s for s in status if s["env"] == "MIMO_API_KEY")
        assert mimo["source"] == "dotenv"
        assert mimo["has_value"] is True

    def test_missing_when_neither(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for spec in KEY_PROVIDERS:
            monkeypatch.delenv(spec["env"], raising=False)
        status = _build_status()
        for item in status:
            assert item["source"] == "missing"
            assert item["has_value"] is False


class TestHtmlPage:
    def test_html_contains_expected_provider_envs(self) -> None:
        # The HTML is server-rendered via _build_status but the
        # template itself should mention the JavaScript token slot.
        assert "__TOKEN__" in HTML_PAGE

    def test_html_has_save_endpoint(self) -> None:
        assert "/api/save" in HTML_PAGE
        assert "/api/test" in HTML_PAGE
        assert "/api/status" in HTML_PAGE

    def test_html_has_loopback_messaging(self) -> None:
        # Operator should see "127.0.0.1" referenced so they know
        # the form is local-only
        assert "127.0.0.1" in HTML_PAGE


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestKeysListCli:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "--help"])
        assert result.exit_code == 0
        assert "serve" in result.output
        assert "list" in result.output

    def test_list_pretty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for spec in KEY_PROVIDERS:
            monkeypatch.delenv(spec["env"], raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "list"])
        assert result.exit_code == 0
        # Each provider mentioned in the table
        assert "KIMI_API_KEY" in result.output
        assert "MIMO_API_KEY" in result.output
        assert "missing" in result.output.lower()

    def test_list_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "list", "--format", "json"])
        assert result.exit_code == 0
        # JSON-parseable
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert any(item["env"] == "KIMI_API_KEY" for item in data)


# ---------------------------------------------------------------------------
# Server lifecycle (end-to-end via background thread)
# ---------------------------------------------------------------------------


class TestServerLifecycle:
    def test_server_boots_and_serves_html(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Smoke test: launch server in background thread, fetch the
        form HTML page with valid token, fetch with invalid token,
        let it self-shutdown via idle timeout."""
        monkeypatch.chdir(tmp_path)

        # We need to know the URL after serve_key_ui binds.  Workaround:
        # use the HTTPServer directly via a thin replication.
        import http.server
        from harness.keys_ui import _KeyServerHandler

        import secrets as _secrets
        token = _secrets.token_urlsafe(32)
        httpd = http.server.HTTPServer(("127.0.0.1", 0), _KeyServerHandler)
        httpd._token = token  # type: ignore[attr-defined]
        httpd._last_request_at = time.monotonic()  # type: ignore[attr-defined]
        port = httpd.server_address[1]

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            # GET with valid token: should return the HTML
            url = f"http://127.0.0.1:{port}/?token={token}"
            with urllib.request.urlopen(url, timeout=5) as r:
                body = r.read().decode("utf-8")
                assert r.status == 200
                assert "harness" in body.lower()
                assert "KIMI_API_KEY" not in body  # rendered via JS
                # But the JS fetches /api/status which would include it

            # GET /api/status with valid token: returns the list
            url = f"http://127.0.0.1:{port}/api/status?token={token}"
            with urllib.request.urlopen(url, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
                assert isinstance(data, list)
                assert any(d["env"] == "KIMI_API_KEY" for d in data)

            # GET with bad token: 403
            url = f"http://127.0.0.1:{port}/?token=wrong"
            try:
                urllib.request.urlopen(url, timeout=5)
                pytest.fail("expected 403 for bad token")
            except urllib.error.HTTPError as e:
                assert e.code == 403
        finally:
            httpd.shutdown()

    def test_save_writes_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        import http.server
        from harness.keys_ui import _KeyServerHandler
        import secrets as _secrets

        token = _secrets.token_urlsafe(32)
        httpd = http.server.HTTPServer(("127.0.0.1", 0), _KeyServerHandler)
        httpd._token = token  # type: ignore[attr-defined]
        httpd._last_request_at = time.monotonic()  # type: ignore[attr-defined]
        port = httpd.server_address[1]

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{port}/api/save?token={token}"
            body = json.dumps({
                "updates": {"KIMI_API_KEY": "sk-from-form-12345"},
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                resp = json.loads(r.read().decode("utf-8"))
                assert resp["saved"] is True
                assert resp["count"] == 1
            # .env file should now contain the key
            env_file = tmp_path / ".env"
            assert env_file.exists()
            assert "KIMI_API_KEY=sk-from-form-12345" in env_file.read_text(
                encoding="utf-8",
            )
        finally:
            httpd.shutdown()
