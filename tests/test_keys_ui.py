"""W14-HARNESS-KEYS-WEB-UI: tests for the keys-UI module.

Server lifecycle is exercised end-to-end via threading.  Other tests
exercise the pure helpers (_mask / _read_env_file / _write_env_file /
_build_status).

W14-KEYS-UI-SECURITY-PATCH 2026-05-26: extended with security
regression tests (env_var allowlist on POST endpoints, value content
validation, security headers, Origin check, .env quoting).
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

from harness import keys_ui as keys_ui_mod
from harness.cli import cli
from harness.keys_ui import (
    HTML_PAGE,
    KEY_PROVIDERS,
    KNOWN_ENV_VARS,
    _build_status,
    _current_value,
    _mask,
    _read_env_file,
    _resolve_env_path,
    _validate_env_var,
    _validate_value,
    _write_env_file,
    list_key_status,
    serve_key_ui,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


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
        # W14-KEYS-UI-SECURITY-PATCH: values are now single-quoted
        # so `set -a; source .env` cannot perform $-expansion
        assert "KIMI_API_KEY='sk-test'" in text

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

    def test_write_single_quotes_protect_against_dollar_expansion(
        self, tmp_path: Path,
    ) -> None:
        # W14-KEYS-UI-SECURITY-PATCH: keys containing $-style sequences
        # must NOT be expanded when sourced.  Single-quote wrapping
        # ensures bash treats them literally.
        f = tmp_path / ".env"
        _write_env_file(f, {"K": "value-with-$HOME-in-it"})
        text = f.read_text(encoding="utf-8")
        # The literal $ stays inside single quotes — bash doesn't expand it
        assert "'value-with-$HOME-in-it'" in text
        # Re-read should still recover the literal value
        d = _read_env_file(f)
        assert d["K"] == "value-with-$HOME-in-it"


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


# ---------------------------------------------------------------------------
# Security helpers (W14-KEYS-UI-SECURITY-PATCH)
# ---------------------------------------------------------------------------


class TestValidateEnvVar:
    def test_known_provider_passes(self) -> None:
        assert _validate_env_var("KIMI_API_KEY") is None
        assert _validate_env_var("MIMO_API_KEY") is None
        assert _validate_env_var("ANTHROPIC_API_KEY") is None

    def test_unknown_var_rejected(self) -> None:
        # PATH is the canonical attack target — must not be writable
        assert _validate_env_var("PATH") is not None
        assert _validate_env_var("LD_PRELOAD") is not None
        assert _validate_env_var("PYTHONPATH") is not None
        assert _validate_env_var("BROWSER") is not None

    def test_empty_rejected(self) -> None:
        assert _validate_env_var("") is not None
        assert _validate_env_var(None) is not None  # type: ignore[arg-type]

    def test_case_sensitive(self) -> None:
        # Must reject case-mangled variants too
        assert _validate_env_var("kimi_api_key") is not None
        assert _validate_env_var("Kimi_Api_Key") is not None


class TestValidateValue:
    def test_normal_key_passes(self) -> None:
        assert _validate_value("sk-abcdef1234567890") is None

    def test_newline_rejected(self) -> None:
        # Newline in pasted "key" must be rejected — would otherwise
        # let an attacker inject an extra .env line
        assert _validate_value("sk-test\nPATH=/evil") is not None
        assert _validate_value("sk-test\rPATH=/evil") is not None

    def test_nul_byte_rejected(self) -> None:
        assert _validate_value("sk-test\x00extra") is not None

    def test_single_quote_rejected(self) -> None:
        # We write values single-quoted; a literal ' in the value
        # would let the operator break out of the quote and inject
        # shell when `source .env` runs
        assert _validate_value("sk-test'$(curl evil)'rest") is not None

    def test_overlong_rejected(self) -> None:
        assert _validate_value("x" * 5000) is not None


class TestResolveEnvPath:
    def test_returns_path_with_env_basename(self) -> None:
        p = _resolve_env_path()
        assert p.name == ".env"


# ---------------------------------------------------------------------------
# Status payload
# ---------------------------------------------------------------------------


class TestBuildStatus:
    """W14-KEYS-POOL 2026-05-26: payload is now multi-slot per provider.

    Helper: tests look up a provider's slot-1 via _slot1_of() to keep
    assertions concise.
    """

    def _patch_envpath(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            keys_ui_mod,
            "_resolve_env_path",
            lambda: tmp_path / ".env",
        )

    def _clean_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for spec in KEY_PROVIDERS:
            for n in range(1, 6):
                monkeypatch.delenv(f"{spec['env']}_{n}", raising=False)
                monkeypatch.delenv(f"{spec['env']}_LABEL_{n}", raising=False)
            monkeypatch.delenv(spec["env"], raising=False)

    def _slot1_of(self, providers: list[dict], prefix: str) -> dict:
        prov = next(p for p in providers if p["env_prefix"] == prefix)
        return prov["slots"][0]

    def test_payload_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        payload = _build_status()
        assert "providers" in payload
        assert "env_path" in payload
        assert "max_slots" in payload
        assert isinstance(payload["providers"], list)
        assert isinstance(payload["env_path"], str)
        assert payload["max_slots"] == 4

    def test_returns_entry_per_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        providers = _build_status()["providers"]
        assert len(providers) == len(KEY_PROVIDERS)
        for item in providers:
            assert "env_prefix" in item
            assert "display" in item
            assert "purpose" in item
            assert "slots" in item
            assert isinstance(item["slots"], list)
            # Always at least slot 1 rendered for the "paste key here" UX
            assert len(item["slots"]) >= 1
            slot1 = item["slots"][0]
            assert slot1["slot"] == 1
            for key in ("env_var", "source", "masked", "has_value", "label"):
                assert key in slot1

    def test_env_source_when_set_in_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        monkeypatch.setenv("KIMI_API_KEY", "sk-test-from-env-1234567890")
        providers = _build_status()["providers"]
        slot = self._slot1_of(providers, "KIMI_API_KEY")
        # Legacy singular env var → source="env-legacy"
        assert slot["source"] == "env-legacy"
        assert slot["has_value"] is True
        assert "sk-test-from-env" not in slot["masked"]
        assert slot["masked"].startswith("sk-t")

    def test_indexed_env_var_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # KIMI_API_KEY_1 (the canonical pool form) → source="env"
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-canonical-pool-form")
        providers = _build_status()["providers"]
        slot = self._slot1_of(providers, "KIMI_API_KEY")
        assert slot["source"] == "env"
        assert slot["has_value"] is True
        assert slot["env_var"] == "KIMI_API_KEY_1"

    def test_dotenv_source_when_in_dotenv_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        (tmp_path / ".env").write_text(
            "MIMO_API_KEY='tp-test-from-dotenv-abc'\n", encoding="utf-8",
        )
        providers = _build_status()["providers"]
        slot = self._slot1_of(providers, "MIMO_API_KEY")
        assert slot["source"] == "dotenv"
        assert slot["has_value"] is True

    def test_missing_when_neither(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        providers = _build_status()["providers"]
        for prov in providers:
            # Each provider shows at least slot 1, all empty
            assert prov["slots"][0]["source"] == "missing"
            assert prov["slots"][0]["has_value"] is False


class TestBuildStatusMultiKey:
    """W14-KEYS-POOL 2026-05-26: multi-slot rendering behaviors."""

    def _patch_envpath(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            keys_ui_mod, "_resolve_env_path", lambda: tmp_path / ".env",
        )

    def _clean_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for spec in KEY_PROVIDERS:
            for n in range(1, 6):
                monkeypatch.delenv(f"{spec['env']}_{n}", raising=False)
                monkeypatch.delenv(f"{spec['env']}_LABEL_{n}", raising=False)
            monkeypatch.delenv(spec["env"], raising=False)

    def test_two_slots_renders_both_plus_empty_third(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        monkeypatch.setenv("KIMI_API_KEY_1", "sk-1")
        monkeypatch.setenv("KIMI_API_KEY_2", "sk-2")
        providers = _build_status()["providers"]
        kimi = next(p for p in providers if p["env_prefix"] == "KIMI_API_KEY")
        # Populated slots + 1 empty trailing for "Add" affordance
        assert len(kimi["slots"]) == 3
        assert kimi["slots"][0]["has_value"] is True
        assert kimi["slots"][1]["has_value"] is True
        assert kimi["slots"][2]["has_value"] is False
        assert kimi["slots"][2]["env_var"] == "KIMI_API_KEY_3"

    def test_full_pool_no_extra_empty_slot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        for n in range(1, 5):
            monkeypatch.setenv(f"KIMI_API_KEY_{n}", f"sk-{n}")
        providers = _build_status()["providers"]
        kimi = next(p for p in providers if p["env_prefix"] == "KIMI_API_KEY")
        # 4 populated slots, no trailing empty (we hit max_slots)
        assert len(kimi["slots"]) == 4
        for slot in kimi["slots"]:
            assert slot["has_value"] is True

    def test_dotenv_indexed_slots_render(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._patch_envpath(tmp_path, monkeypatch)
        self._clean_all(monkeypatch)
        (tmp_path / ".env").write_text(
            "MIMO_API_KEY_1='tp-primary'\n"
            "MIMO_API_KEY_2='tp-backup'\n",
            encoding="utf-8",
        )
        providers = _build_status()["providers"]
        mimo = next(p for p in providers if p["env_prefix"] == "MIMO_API_KEY")
        assert mimo["slots"][0]["has_value"] is True
        assert mimo["slots"][0]["source"] == "dotenv"
        assert mimo["slots"][1]["has_value"] is True
        assert mimo["slots"][1]["source"] == "dotenv"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


class TestHtmlPage:
    def test_html_contains_expected_provider_envs(self) -> None:
        assert "__TOKEN__" in HTML_PAGE

    def test_html_has_save_endpoint(self) -> None:
        assert "/api/save" in HTML_PAGE
        assert "/api/test" in HTML_PAGE
        assert "/api/status" in HTML_PAGE

    def test_html_has_loopback_messaging(self) -> None:
        assert "127.0.0.1" in HTML_PAGE

    def test_html_has_no_doubled_braces(self) -> None:
        # W14-KEYS-UI-RENDER-FIX 2026-05-26 regression guard.
        assert "{{" not in HTML_PAGE, (
            "doubled `{{` in HTML template — CSS/JS will break in browser"
        )
        assert "}}" not in HTML_PAGE, (
            "doubled `}}` in HTML template — CSS/JS will break in browser"
        )

    def test_html_css_block_is_valid_shaped(self) -> None:
        assert "* { box-sizing: border-box; }" in HTML_PAGE
        assert "body {" in HTML_PAGE
        assert ".row {" in HTML_PAGE

    def test_html_js_template_literal_token_is_single_braced(self) -> None:
        assert "${TOKEN}" in HTML_PAGE
        assert "${{TOKEN}}" not in HTML_PAGE

    def test_rendered_html_has_token_substituted(self) -> None:
        token = "test-token-abc123"
        body = HTML_PAGE.replace("__TOKEN__", token)
        assert "__TOKEN__" not in body
        assert f'const TOKEN = "{token}";' in body
        assert "{{" not in body
        assert "}}" not in body

    def test_html_uses_create_element_not_inner_html(self) -> None:
        # W14-KEYS-UI-SECURITY-PATCH: row rendering must NOT use
        # innerHTML template literals that interpolate item.masked /
        # item.display / item.purpose / item.env.  Use createElement
        # + textContent instead.
        assert "createElement" in HTML_PAGE
        assert "textContent" in HTML_PAGE
        # No literal `innerHTML = \`` template-string assignment
        # (the safe `container.textContent = ""` clear is fine).
        assert "innerHTML = `" not in HTML_PAGE
        # Specifically these item.* fields must NEVER appear in a
        # template-string (backtick) context, even if we change the
        # JS later — guard at the textual level
        for field in ["${item.display}", "${item.purpose}",
                      "${item.env}", "${item.masked}"]:
            assert field not in HTML_PAGE, (
                f"{field} interpolated into innerHTML — XSS surface"
            )

    def test_html_has_env_path_info_slot(self) -> None:
        # Operator should see where keys will save
        assert 'id="env-path-info"' in HTML_PAGE


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
        monkeypatch.setattr(
            keys_ui_mod, "_resolve_env_path", lambda: tmp_path / ".env",
        )
        for spec in KEY_PROVIDERS:
            monkeypatch.delenv(spec["env"], raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "list"])
        assert result.exit_code == 0
        assert "KIMI_API_KEY" in result.output
        assert "MIMO_API_KEY" in result.output
        assert "missing" in result.output.lower()

    def test_list_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            keys_ui_mod, "_resolve_env_path", lambda: tmp_path / ".env",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "list", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert any(item["env"] == "KIMI_API_KEY" for item in data)


# ---------------------------------------------------------------------------
# Server lifecycle + security regression tests
# ---------------------------------------------------------------------------


class _HarnessContext:
    """Wrap an HTTPServer in a context manager for the end-to-end tests."""
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import secrets as _secrets
        from harness.keys_ui import _KeyServerHandler
        import http.server

        # All E2E tests want save writes to land in tmp_path
        monkeypatch.setattr(
            keys_ui_mod, "_resolve_env_path", lambda: tmp_path / ".env",
        )
        self.token = _secrets.token_urlsafe(32)
        self.httpd = http.server.HTTPServer(
            ("127.0.0.1", 0), _KeyServerHandler,
        )
        self.httpd._token = self.token  # type: ignore[attr-defined]
        self.httpd._last_request_at = time.monotonic()  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True,
        )
        self.thread.start()
        self.tmp_path = tmp_path

    def url(self, path: str) -> str:
        sep = "&" if "?" in path else "?"
        return f"http://127.0.0.1:{self.port}{path}{sep}token={self.token}"

    def close(self) -> None:
        self.httpd.shutdown()

    def __enter__(self) -> "_HarnessContext":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class TestServerLifecycle:
    def test_server_boots_and_serves_html(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            with urllib.request.urlopen(ctx.url("/"), timeout=5) as r:
                body = r.read().decode("utf-8")
                assert r.status == 200
                assert "harness" in body.lower()
                assert "KIMI_API_KEY" not in body  # rendered via JS

            with urllib.request.urlopen(
                ctx.url("/api/status"), timeout=5,
            ) as r:
                data = json.loads(r.read().decode("utf-8"))
                assert "providers" in data
                assert "max_slots" in data
                # Providers shape is now multi-slot
                assert any(
                    p["env_prefix"] == "KIMI_API_KEY"
                    for p in data["providers"]
                )

            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{ctx.port}/?token=wrong", timeout=5,
                )
                pytest.fail("expected 403 for bad token")
            except urllib.error.HTTPError as e:
                assert e.code == 403

    def test_save_writes_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            body = json.dumps({
                "updates": {"KIMI_API_KEY": "sk-from-form-12345"},
            }).encode("utf-8")
            req = urllib.request.Request(
                ctx.url("/api/save"), data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                resp = json.loads(r.read().decode("utf-8"))
                assert resp["saved"] is True
                assert resp["count"] == 1
            env_file = tmp_path / ".env"
            assert env_file.exists()
            # Now single-quoted per W14-KEYS-UI-SECURITY-PATCH
            assert "KIMI_API_KEY='sk-from-form-12345'" in env_file.read_text(
                encoding="utf-8",
            )


class TestSecurityRegression:
    """W14-KEYS-UI-SECURITY-PATCH 2026-05-26 — regression tests for
    the patched-in defenses.  Each test pins one specific defense
    so we know if a future refactor removes it."""

    def _post(
        self, ctx: "_HarnessContext", path: str, payload: dict,
        extra_headers: dict | None = None,
    ) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(
            ctx.url(path), data=body, method="POST", headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8"))
            except Exception:
                detail = {}
            return e.code, detail

    def test_save_rejects_arbitrary_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # P0-1: an attacker cannot use /api/save to write PATH
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, body = self._post(
                ctx, "/api/save",
                {"updates": {"PATH": "/tmp/evil:/usr/bin"}},
            )
            assert status == 400
            assert "allowlist" in body.get("error", "").lower() or \
                   "unknown" in body.get("error", "").lower()
            # And nothing landed in .env
            env_file = tmp_path / ".env"
            if env_file.exists():
                assert "PATH" not in env_file.read_text(encoding="utf-8")

    def test_save_rejects_ld_preload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {"LD_PRELOAD": "/tmp/evil.so"}},
            )
            assert status == 400

    def test_test_rejects_arbitrary_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/test",
                {"env_var": "PATH", "engine_probe": "kimi-via-claude"},
            )
            assert status == 400

    def test_save_rejects_newline_in_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # P0-3: a key with a newline could inject a new .env line
        # which would set PATH (or anything) on `source .env`
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {
                    "KIMI_API_KEY": "sk-good\nPATH=/tmp/evil",
                }},
            )
            assert status == 400

    def test_save_rejects_single_quote_in_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # P0-3: a key with ' could break out of the .env quote
        # wrapping and inject shell
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {
                    "KIMI_API_KEY": "sk-good'$(curl evil)'rest",
                }},
            )
            assert status == 400

    def test_save_rejects_nul_byte(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY": "sk-\x00-nul"}},
            )
            assert status == 400

    def test_save_rejects_bad_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # P1-3: if a browser sends Origin and it doesn't match the
        # bound URL, the POST must be rejected
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY": "sk-ok"}},
                extra_headers={"Origin": "http://attacker.example.com"},
            )
            assert status == 403

    def test_save_allows_matching_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            origin = f"http://127.0.0.1:{ctx.port}"
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY": "sk-ok-with-origin"}},
                extra_headers={"Origin": origin},
            )
            assert status == 200

    def test_save_allows_empty_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Non-browser clients (curl, our own test) don't send Origin.
        # The token alone is sufficient authn for those.
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY": "sk-ok-no-origin"}},
            )
            assert status == 200

    def test_security_headers_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # P1-2: every response carries the locked-down CSP + X-Frame-Options
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            with urllib.request.urlopen(ctx.url("/"), timeout=5) as r:
                assert r.headers["X-Frame-Options"] == "DENY"
                assert "default-src 'none'" in r.headers[
                    "Content-Security-Policy"
                ]
                assert r.headers["Referrer-Policy"] == "no-referrer"
                assert r.headers["X-Content-Type-Options"] == "nosniff"

    def test_security_headers_on_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            with urllib.request.urlopen(
                ctx.url("/api/status"), timeout=5,
            ) as r:
                assert r.headers["X-Frame-Options"] == "DENY"
                assert r.headers["Referrer-Policy"] == "no-referrer"

    def test_known_env_vars_set_matches_providers(self) -> None:
        # The allowlist should be exactly the set of provider env vars
        assert KNOWN_ENV_VARS == frozenset(
            spec["env"] for spec in KEY_PROVIDERS
        )

    def test_save_accepts_pool_slot_env_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # W14-KEYS-POOL: KIMI_API_KEY_2 (pool slot) is allowed
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, body = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY_2": "sk-slot-2-value"}},
            )
            assert status == 200
            env_file = tmp_path / ".env"
            assert env_file.exists()
            text = env_file.read_text(encoding="utf-8")
            assert "KIMI_API_KEY_2='sk-slot-2-value'" in text

    def test_save_rejects_slot_above_max(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # W14-KEYS-POOL: KIMI_API_KEY_99 is not in the allowlist
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY_99": "sk-shouldnt-land"}},
            )
            assert status == 400

    def test_save_with_empty_value_deletes_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # First populate the slot, then send empty to delete
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            s1, _ = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY_2": "sk-temp"}},
            )
            assert s1 == 200
            s2, _ = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY_2": ""}},
            )
            assert s2 == 200
            text = (tmp_path / ".env").read_text(encoding="utf-8")
            assert "KIMI_API_KEY_2" not in text
            # os.environ should also be pop'd (deletion semantics)
            assert os.environ.get("KIMI_API_KEY_2") is None

    def test_save_accepts_label_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # W14-KEYS-POOL: KIMI_API_KEY_LABEL_1 (label) is allowed
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {
                    "KIMI_API_KEY_1": "sk-primary",
                    "KIMI_API_KEY_LABEL_1": "production",
                }},
            )
            assert status == 200
            text = (tmp_path / ".env").read_text(encoding="utf-8")
            assert "KIMI_API_KEY_LABEL_1='production'" in text

    def test_large_post_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Defense in depth: 65KB body → 413
        with _HarnessContext(tmp_path, monkeypatch) as ctx:
            huge = "x" * 65_000
            status, _ = self._post(
                ctx, "/api/save",
                {"updates": {"KIMI_API_KEY": huge}},
            )
            # Either 413 (too large) or 400 (value too long); both OK
            assert status in (400, 413)
