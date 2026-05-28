"""W14-KEY-ROTATION-PLAYBOOK 2026-05-28: tests for rotate_secret + env-rotate CLI.

Covers:

- rotate_secret happy path (existing value preserved, new value live)
- rotate_secret with keep_previous=False (no backup written)
- rotate_secret on first-time write (no previous to preserve)
- rotate_secret raises on empty name / empty value
- rotate_secret never leaks the new value in the returned dict
- append_key_rotation_event participates in the chain
- harness env-rotate CLI: unknown engine, empty key, scripted stdin path
- harness env-rotate CLI: dry-run
- engine → env-var mapping

Windows-only tests are skipped on POSIX since DPAPI is unavailable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32",
    reason="DPAPI is Windows-only; rotation surface tested via mocks elsewhere",
)


# ---------------------------------------------------------------------------
# Engine → env var mapping (cross-platform)
# ---------------------------------------------------------------------------


class TestEngineMapping:
    """Spot-check the operator-facing short names map to canonical env vars."""

    def test_qwen_maps_to_dashscope(self) -> None:
        from harness.cli import _ROTATE_ENGINE_TO_ENV
        assert _ROTATE_ENGINE_TO_ENV["qwen"] == "DASHSCOPE_API_KEY"

    def test_kimi_maps_to_kimi_api_key(self) -> None:
        from harness.cli import _ROTATE_ENGINE_TO_ENV
        assert _ROTATE_ENGINE_TO_ENV["kimi"] == "KIMI_API_KEY"

    def test_all_engines_have_env_var(self) -> None:
        from harness.cli import _ROTATE_ENGINE_TO_ENV
        expected = {"deepseek", "kimi", "mimo", "anthropic", "gemini", "qwen"}
        assert set(_ROTATE_ENGINE_TO_ENV) == expected


# ---------------------------------------------------------------------------
# rotate_secret — DPAPI primitive (Windows only)
# ---------------------------------------------------------------------------


@WINDOWS_ONLY
class TestRotateSecret:
    """DPAPI rotation primitive — exercises the real DPAPI on Windows."""

    def setup_method(self) -> None:
        from harness.secrets.dpapi import delete_secret, list_secrets
        # Clean any prior test state.
        for name in list_secrets():
            if name.startswith("_TEST_ROTATE_"):
                delete_secret(name)

    def teardown_method(self) -> None:
        from harness.secrets.dpapi import delete_secret, list_secrets
        for name in list_secrets():
            if name.startswith("_TEST_ROTATE_"):
                delete_secret(name)

    def test_first_time_write_no_previous(self) -> None:
        from harness.secrets.dpapi import rotate_secret, decrypt_secret
        result = rotate_secret("_TEST_ROTATE_NEW_KEY", "newval-1")
        assert result["rotated"] == "_TEST_ROTATE_NEW_KEY"
        assert result["had_previous_value"] is False
        assert result["previous_kept_as"] is None
        assert decrypt_secret("_TEST_ROTATE_NEW_KEY") == "newval-1"

    def test_rotation_preserves_previous(self) -> None:
        from harness.secrets.dpapi import (
            decrypt_secret, encrypt_secret, rotate_secret,
        )
        encrypt_secret("_TEST_ROTATE_KEY", "oldval-1")
        result = rotate_secret("_TEST_ROTATE_KEY", "newval-2")
        # New value is live
        assert decrypt_secret("_TEST_ROTATE_KEY") == "newval-2"
        # Backup holds the old value
        prev = result["previous_kept_as"]
        assert isinstance(prev, str)
        assert prev.startswith("_TEST_ROTATE_KEY_PREVIOUS_")
        assert decrypt_secret(prev) == "oldval-1"

    def test_rotation_with_no_keep_previous_destroys_old(self) -> None:
        from harness.secrets.dpapi import (
            decrypt_secret, encrypt_secret, list_secrets, rotate_secret,
        )
        encrypt_secret("_TEST_ROTATE_DESTROY", "oldval-3")
        result = rotate_secret("_TEST_ROTATE_DESTROY", "newval-3",
                                keep_previous=False)
        assert result["previous_kept_as"] is None
        assert result["had_previous_value"] is True
        assert decrypt_secret("_TEST_ROTATE_DESTROY") == "newval-3"
        # No _PREVIOUS_ backup exists
        backups = [n for n in list_secrets()
                   if n.startswith("_TEST_ROTATE_DESTROY_PREVIOUS_")]
        assert backups == []

    def test_empty_name_raises(self) -> None:
        from harness.secrets.dpapi import rotate_secret
        with pytest.raises(ValueError, match="name must not be empty"):
            rotate_secret("", "value")

    def test_empty_value_raises(self) -> None:
        from harness.secrets.dpapi import rotate_secret
        with pytest.raises(ValueError, match="value must not be empty"):
            rotate_secret("_TEST_ROTATE_ANY", "")

    def test_result_never_contains_key_value(self) -> None:
        """The returned dict must not leak the new or old value."""
        from harness.secrets.dpapi import encrypt_secret, rotate_secret
        encrypt_secret("_TEST_ROTATE_LEAK", "secret-old")
        result = rotate_secret("_TEST_ROTATE_LEAK", "secret-new")
        json_str = json.dumps(result, default=str)
        assert "secret-old" not in json_str
        assert "secret-new" not in json_str


# ---------------------------------------------------------------------------
# rotate_secret on non-Windows raises NotImplementedError
# ---------------------------------------------------------------------------


class TestRotateSecretNonWindows:
    """Verify the platform guard raises cleanly off Windows."""

    def test_non_windows_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import harness.secrets.dpapi as dpapi
        original_require = dpapi._require_windows

        def fake_require() -> None:
            raise NotImplementedError("simulated non-Windows host")

        monkeypatch.setattr(dpapi, "_require_windows", fake_require)
        with pytest.raises(NotImplementedError):
            dpapi.rotate_secret("ANY", "value")


# ---------------------------------------------------------------------------
# append_key_rotation_event — audit ledger integration
# ---------------------------------------------------------------------------


class TestAppendKeyRotationEvent:
    """The rotation event participates in the W14-AUDIT-CHAIN-HMAC chain."""

    def test_writes_event_to_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from harness.audit_jsonl import append_key_rotation_event
        # Fixed key so chain reproduces
        monkeypatch.setenv(
            "HARNESS_AUDIT_HMAC_KEY",
            "00" * 32,
        )
        p = tmp_path / "rot.jsonl"
        ok = append_key_rotation_event(
            provider="deepseek",
            previous_kept_as="DEEPSEEK_API_KEY_PREVIOUS_20260528120000",
            had_previous_value=True,
            ledger_path=p,
        )
        assert ok is True
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["event"] == "key_rotation"
        assert obj["provider"] == "deepseek"
        assert obj["previous_kept_as"] == "DEEPSEEK_API_KEY_PREVIOUS_20260528120000"
        assert obj["had_previous_value"] is True
        # Chain participation
        assert "prev_hash" in obj
        assert "hmac" in obj

    def test_chain_participates_with_dispatch_events(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Mixed ledger (dispatch + rotation events) verifies cleanly."""
        from harness.audit_chain import verify_chain
        from harness.audit_jsonl import (
            append_dispatch_event,
            append_key_rotation_event,
        )
        monkeypatch.setenv("HARNESS_AUDIT_HMAC_KEY", "11" * 32)
        p = tmp_path / "mixed.jsonl"
        # Dispatch → rotation → dispatch
        append_dispatch_event(
            engine="deepseek", model="m", dispatch_id="d1",
            success=True, error=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, elapsed_ms=1, ledger_path=p,
        )
        append_key_rotation_event(
            provider="deepseek", previous_kept_as=None,
            had_previous_value=False, ledger_path=p,
        )
        append_dispatch_event(
            engine="deepseek", model="m", dispatch_id="d2",
            success=True, error=None, tokens_in=2, tokens_out=2,
            cost_usd=0.0, elapsed_ms=2, ledger_path=p,
        )
        result = verify_chain(p)
        assert result.ok is True
        assert result.chained == 3

    def test_no_key_value_in_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Even with a key value present elsewhere, the event must not log it."""
        from harness.audit_jsonl import append_key_rotation_event
        monkeypatch.setenv("HARNESS_AUDIT_HMAC_KEY", "22" * 32)
        p = tmp_path / "no-leak.jsonl"
        append_key_rotation_event(
            provider="mimo",
            previous_kept_as="MIMO_API_KEY_PREVIOUS_x",
            had_previous_value=True,
            ledger_path=p,
        )
        # No field should contain a key-like value (no sk-, tp-, AIza patterns)
        text = p.read_text(encoding="utf-8")
        for prefix in ["sk-", "tp-", "AIza"]:
            assert prefix not in text


# ---------------------------------------------------------------------------
# CLI — harness env-rotate (cross-platform via mocks)
# ---------------------------------------------------------------------------


class TestEnvRotateCLI:
    """Click CLI behavior — uses CliRunner + mocks to avoid DPAPI."""

    def test_unknown_engine_exit_1(self) -> None:
        from harness.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["env-rotate", "fakeengine"])
        assert result.exit_code == 1
        assert "Unknown engine" in result.output

    def test_unknown_engine_lists_supported(self) -> None:
        from harness.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["env-rotate", "nope"])
        assert "deepseek" in result.output
        assert "qwen" in result.output

    def test_dry_run_no_dpapi_call(self) -> None:
        from harness.cli import cli
        runner = CliRunner()
        with patch("harness.secrets.dpapi.rotate_secret") as m:
            result = runner.invoke(cli, ["env-rotate", "deepseek", "--dry-run"])
        assert result.exit_code == 0
        assert "[dry-run]" in result.output
        assert "DEEPSEEK_API_KEY" in result.output
        assert m.call_count == 0  # no DPAPI write in dry-run

    def test_empty_key_from_stdin_exit_2(self) -> None:
        from harness.cli import cli
        runner = CliRunner()
        result = runner.invoke(
            cli, ["env-rotate", "deepseek", "--from-stdin"],
            input="\n",
        )
        assert result.exit_code == 2
        assert "Empty key" in result.output

    def test_scripted_rotation_via_stdin(self) -> None:
        """Patch rotate_secret + append_key_rotation_event to bypass DPAPI."""
        from harness.cli import cli
        runner = CliRunner()
        with patch("harness.secrets.dpapi.rotate_secret") as rot, \
                patch("harness.audit_jsonl.append_key_rotation_event") as aud:
            rot.return_value = {
                "rotated": "DEEPSEEK_API_KEY",
                "previous_kept_as": "DEEPSEEK_API_KEY_PREVIOUS_20260528000000",
                "timestamp_utc": "2026-05-28T00:00:00Z",
                "had_previous_value": True,
            }
            result = runner.invoke(
                cli, ["env-rotate", "deepseek", "--from-stdin"],
                input="fake-new-key-value\n",
            )
        assert result.exit_code == 0
        assert "Rotated DEEPSEEK_API_KEY" in result.output
        assert "previous kept as" in result.output
        # Verify rotate_secret was called with the new key
        assert rot.call_count == 1
        called_args = rot.call_args
        assert called_args.args[0] == "DEEPSEEK_API_KEY"
        assert called_args.args[1] == "fake-new-key-value"
        # And the audit event was emitted
        assert aud.call_count == 1
        aud_kwargs = aud.call_args.kwargs
        assert aud_kwargs["provider"] == "deepseek"
        assert aud_kwargs["had_previous_value"] is True

    def test_no_keep_previous_passed_through(self) -> None:
        from harness.cli import cli
        runner = CliRunner()
        with patch("harness.secrets.dpapi.rotate_secret") as rot, \
                patch("harness.audit_jsonl.append_key_rotation_event"):
            rot.return_value = {
                "rotated": "MIMO_API_KEY",
                "previous_kept_as": None,
                "timestamp_utc": "2026-05-28T00:00:00Z",
                "had_previous_value": True,
            }
            result = runner.invoke(
                cli,
                ["env-rotate", "mimo", "--from-stdin", "--no-keep-previous"],
                input="newkey\n",
            )
        assert result.exit_code == 0
        # rotate_secret should have been called with keep_previous=False
        assert rot.call_args.kwargs["keep_previous"] is False
        # Output should mention the previous value was discarded
        assert "DISCARDED" in result.output

    def test_first_time_write_no_smoke_test_prev_hint(self) -> None:
        """First-time write: output mentions no previous value existed."""
        from harness.cli import cli
        runner = CliRunner()
        with patch("harness.secrets.dpapi.rotate_secret") as rot, \
                patch("harness.audit_jsonl.append_key_rotation_event"):
            rot.return_value = {
                "rotated": "QWEN_API_KEY",  # synthetic
                "previous_kept_as": None,
                "timestamp_utc": "2026-05-28T00:00:00Z",
                "had_previous_value": False,
            }
            result = runner.invoke(
                cli, ["env-rotate", "qwen", "--from-stdin"],
                input="firstkey\n",
            )
        assert result.exit_code == 0
        assert "first-time write" in result.output

    def test_uppercase_engine_lowered(self) -> None:
        """Engine name is case-insensitive."""
        from harness.cli import cli
        runner = CliRunner()
        with patch("harness.secrets.dpapi.rotate_secret") as rot, \
                patch("harness.audit_jsonl.append_key_rotation_event"):
            rot.return_value = {
                "rotated": "DEEPSEEK_API_KEY",
                "previous_kept_as": None,
                "timestamp_utc": "2026-05-28T00:00:00Z",
                "had_previous_value": False,
            }
            result = runner.invoke(
                cli, ["env-rotate", "DEEPSEEK", "--from-stdin"],
                input="x\n",
            )
        assert result.exit_code == 0
        # Audit log should record the lowercase provider name
