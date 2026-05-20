"""Smoke tests for Wave 4 installer helpers (Python side).

Covers:
- dpapi._cli_set stdin handling
- cli.env integration with DPAPI store
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.secrets.dpapi import _cli_set


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# dpapi CLI helper
# ---------------------------------------------------------------------------


@patch("harness.secrets.dpapi.encrypt_secret")
def test_cli_set_encrypts_and_prints(mock_encrypt, tmp_path: Path) -> None:
    """_cli_set reads stdin, encrypts, and emits NAME: SET."""
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    try:
        sys.stdin = StringIO("sk-secret-key\n")
        sys.stdout = StringIO()
        _cli_set("KIMI_API_KEY")
        output = sys.stdout.getvalue()
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout

    mock_encrypt.assert_called_once_with("KIMI_API_KEY", "sk-secret-key")
    assert "KIMI_API_KEY: SET" in output


@patch("harness.secrets.dpapi.encrypt_secret")
def test_cli_set_blank_input_exits_2(mock_encrypt, tmp_path: Path) -> None:
    """Blank stdin causes exit code 2 without calling encrypt_secret."""
    old_stdin = sys.stdin
    try:
        sys.stdin = StringIO("\n")
        with pytest.raises(SystemExit) as exc_info:
            _cli_set("KIMI_API_KEY")
        assert exc_info.value.code == 2
    finally:
        sys.stdin = old_stdin

    mock_encrypt.assert_not_called()


# ---------------------------------------------------------------------------
# cli.env DPAPI integration
# ---------------------------------------------------------------------------


@patch.dict("os.environ", {}, clear=True)
@patch("harness.secrets.dpapi.has_secret")
def test_env_shows_set_from_dpapi(mock_has, runner: CliRunner) -> None:
    """env shows SET when DPAPI has the secret but env var is absent."""
    mock_has.return_value = True
    result = runner.invoke(cli, ["env"])
    assert result.exit_code == 0
    for key in ("KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
        assert f"{key}: SET" in result.output


@patch.dict("os.environ", {}, clear=True)
@patch("harness.secrets.dpapi.has_secret")
def test_env_shows_missing_when_absent(mock_has, runner: CliRunner) -> None:
    """env shows MISSING when neither env var nor DPAPI secret exists."""
    mock_has.return_value = False
    result = runner.invoke(cli, ["env"])
    assert result.exit_code == 0
    for key in ("KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
        assert f"{key}: MISSING" in result.output


@patch.dict("os.environ", {"KIMI_API_KEY": "sk-live"}, clear=True)
@patch("harness.secrets.dpapi.has_secret")
def test_env_prefers_env_var(mock_has, runner: CliRunner) -> None:
    """env shows SET when only the env var is present."""
    mock_has.return_value = False
    result = runner.invoke(cli, ["env"])
    assert result.exit_code == 0
    assert "KIMI_API_KEY: SET" in result.output
    assert "DEEPSEEK_API_KEY: MISSING" in result.output
    assert "ANTHROPIC_API_KEY: MISSING" in result.output


# ---------------------------------------------------------------------------
# dpapi __main__ block
# ---------------------------------------------------------------------------


def test_main_block_usage_error(capsys) -> None:
    """Calling __main__ with bad args prints usage and exits 2."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "harness.secrets.dpapi"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_main_block_set_invokes_cli_set() -> None:
    """python -m harness.secrets.dpapi set NAME encrypts via stdin.

    This uses a real subprocess so the mock cannot intercept the call;
    we verify only the stdout / exit code.
    """
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "harness.secrets.dpapi", "set", "TEST_KEY"],
        input="my-value\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "TEST_KEY: SET" in result.stdout
