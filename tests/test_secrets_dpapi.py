"""Boundary tests for secrets/dpapi module (Wave B/2.dpapi).

DPAPI ctypes calls are mocked so the tests do not exercise real Windows
cryptography — they verify the Python orchestration layer only.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# This module imports Windows-only dependencies (ctypes.windll).  On
# non-Windows platforms the import fails at *collection* time, which the
# ubuntu CI leg counts as an error.  DPAPI is Windows-only by design (see the
# NotImplementedError it raises elsewhere), so skip the whole module on
# non-Windows rather than emit a false failure.
if sys.platform != "win32":  # pragma: no cover - platform guard
    pytest.skip(
        "DPAPI is Windows-only (ctypes.windll)", allow_module_level=True
    )

from harness.errors import ConfigCorruption
import harness.secrets.dpapi as dpapi
from harness.secrets.dpapi import (
    _cli_set,
    _load_data,
    _save_data,
    delete_secret,
    decrypt_secret,
    encrypt_secret,
    has_secret,
    list_secrets,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_secrets_file(monkeypatch, tmp_path: Path):
    """Redirect the secrets storage path into a temporary directory."""
    secrets_file = tmp_path / "secrets.dpapi"
    monkeypatch.setattr(
        "harness.secrets.dpapi._secrets_path", lambda: secrets_file
    )
    yield


# ---------------------------------------------------------------------------
# 1. encrypt / decrypt roundtrip (identity mocks)
# ---------------------------------------------------------------------------


@patch("harness.secrets.dpapi._dpapi_encrypt", lambda p: p)
@patch("harness.secrets.dpapi._dpapi_decrypt", lambda c: c)
def test_encrypt_decrypt_roundtrip() -> None:
    """encrypt_secret stores base64(ciphertext); decrypt_secret recovers plaintext."""
    plaintext = "harness-test-secret"
    encrypt_secret("TEST_KEY", plaintext)

    # JSON store holds a name → base64 mapping
    data = _load_data()
    assert "TEST_KEY" in data
    expected_b64 = base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
    assert data["TEST_KEY"] == expected_b64

    # Decrypt returns the original value
    assert decrypt_secret("TEST_KEY") == plaintext


# ---------------------------------------------------------------------------
# 2. empty name → ValueError
# ---------------------------------------------------------------------------


def test_encrypt_secret_empty_name_raises() -> None:
    with pytest.raises(ValueError, match="Secret name must not be empty"):
        encrypt_secret("", "some-value")


# ---------------------------------------------------------------------------
# 3. list_secrets returns only names
# ---------------------------------------------------------------------------


@patch("harness.secrets.dpapi._dpapi_encrypt", lambda p: p)
@patch("harness.secrets.dpapi._dpapi_decrypt", lambda c: c)
def test_list_secrets_returns_names_only() -> None:
    encrypt_secret("KEY_A", "value-a")
    encrypt_secret("KEY_B", "value-b")

    names = list_secrets()
    assert set(names) == {"KEY_A", "KEY_B"}

    # No plaintext must leak into the result
    result_json = json.dumps(names)
    assert "value-a" not in result_json
    assert "value-b" not in result_json


# ---------------------------------------------------------------------------
# 4. has_secret lifecycle
# ---------------------------------------------------------------------------


@patch("harness.secrets.dpapi._dpapi_encrypt", lambda p: p)
@patch("harness.secrets.dpapi._dpapi_decrypt", lambda c: c)
def test_has_secret_lifecycle() -> None:
    assert has_secret("X") is False

    encrypt_secret("X", "x-value")
    assert has_secret("X") is True

    delete_secret("X")
    assert has_secret("X") is False


# ---------------------------------------------------------------------------
# 5. delete removes entry; decrypt returns None
# ---------------------------------------------------------------------------


@patch("harness.secrets.dpapi._dpapi_encrypt", lambda p: p)
@patch("harness.secrets.dpapi._dpapi_decrypt", lambda c: c)
def test_delete_secret_removes_entry() -> None:
    encrypt_secret("X", "x-value")
    assert decrypt_secret("X") == "x-value"

    delete_secret("X")
    assert decrypt_secret("X") is None


# ---------------------------------------------------------------------------
# 6. corrupted file → ConfigCorruption
# ---------------------------------------------------------------------------


def test_load_data_corrupted_file_raises() -> None:
    path = dpapi._secrets_path()
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ConfigCorruption):
        _load_data()


# ---------------------------------------------------------------------------
# 7. _save_data atomicity (tempfile + os.replace)
# ---------------------------------------------------------------------------


@patch("harness.secrets.dpapi.os.chmod")
@patch("harness.secrets.dpapi.os.fsync")
@patch("harness.secrets.dpapi.os.replace")
@patch("harness.secrets.dpapi.os.fdopen")
@patch("harness.secrets.dpapi.tempfile.mkstemp")
def test_save_data_atomicity(
    mock_mkstemp,
    mock_fdopen,
    mock_replace,
    mock_fsync,
    mock_chmod,
) -> None:
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=mock_file)
    mock_file.__exit__ = MagicMock(return_value=None)
    mock_file.fileno.return_value = 99
    mock_fdopen.return_value = mock_file

    mock_mkstemp.return_value = (42, "/tmp/._secrets_abc123")

    _save_data({"foo": "bar"})

    mock_mkstemp.assert_called_once_with(
        dir=dpapi._secrets_path().parent, prefix="._secrets_"
    )
    mock_fdopen.assert_called_once_with(42, "w", encoding="utf-8")
    mock_file.flush.assert_called_once()
    mock_fsync.assert_called_once_with(99)
    mock_replace.assert_called_once_with(
        "/tmp/._secrets_abc123", dpapi._secrets_path()
    )
    mock_chmod.assert_called_once_with(dpapi._secrets_path(), 0o600)


# ---------------------------------------------------------------------------
# 8. _cli_set reads stdin, encrypts, prints NAME: SET
# ---------------------------------------------------------------------------


@patch("harness.secrets.dpapi.encrypt_secret")
def test_cli_set_from_stdin(mock_encrypt, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO("my-value\n"))
    monkeypatch.setattr(sys, "stdout", StringIO())

    _cli_set("TEST_KEY")

    mock_encrypt.assert_called_once_with("TEST_KEY", "my-value")
    assert "TEST_KEY: SET" in sys.stdout.getvalue()


# ---------------------------------------------------------------------------
# 9. _cli_set blank stdin → exit 2
# ---------------------------------------------------------------------------


@patch("harness.secrets.dpapi.encrypt_secret")
def test_cli_set_blank_stdin_exits_2(mock_encrypt, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO("\n"))

    with pytest.raises(SystemExit) as exc_info:
        _cli_set("TEST_KEY")

    assert exc_info.value.code == 2
    mock_encrypt.assert_not_called()
