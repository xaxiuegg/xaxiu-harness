"""P16 (2026-05-29): live Windows User-scope key resolution.

Fixes the env-snapshot staleness class — a long-running process keeps the
KIMI_API_KEY (etc.) it was launched with, so a key the operator rotates in
User-scope afterwards never reaches it.  resolve_key(prefer_live_user=True)
reads the live registry value; get_engine opts in for real runs but NOT under
pytest (so tests stay deterministic + cross-platform).
"""
from harness.secrets import resolve as R
from harness.engines import concrete as C


def test_resolve_key_prefer_live_user_wins_over_stale_env(monkeypatch):
    monkeypatch.setenv("FAKE_KEY_P16", "stale-process")
    monkeypatch.setattr(
        R, "live_user_env",
        lambda n: "fresh-user" if n == "FAKE_KEY_P16" else None,
    )
    assert R.resolve_key("FAKE_KEY_P16", prefer_live_user=True) == "fresh-user"


def test_resolve_key_default_keeps_env_wins(monkeypatch):
    # Default (prefer_live_user=False) preserves env-always-wins for CI/shell.
    monkeypatch.setenv("FAKE_KEY_P16", "stale-process")
    monkeypatch.setattr(R, "live_user_env", lambda n: "fresh-user")
    assert R.resolve_key("FAKE_KEY_P16") == "stale-process"


def test_resolve_key_prefer_live_falls_back_when_live_absent(monkeypatch):
    monkeypatch.setenv("FAKE_KEY_P16", "process-only")
    monkeypatch.setattr(R, "live_user_env", lambda n: None)
    assert R.resolve_key("FAKE_KEY_P16", prefer_live_user=True) == "process-only"


def test_live_user_env_non_windows_returns_none(monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "linux")
    assert R.live_user_env("ANYTHING") is None


def test_prefer_live_user_gate_disabled_under_pytest():
    # We are running under pytest, so the gate must be OFF (tests use env).
    assert C._prefer_live_user() is False


def test_prefer_live_user_gate_enabled_outside_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert C._prefer_live_user() is True
