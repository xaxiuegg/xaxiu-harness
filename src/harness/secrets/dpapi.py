"""Windows DPAPI-based encrypted secret storage for xaxiu-harness.

This module implements the v1.2 HIGH-8 amendment: API keys are encrypted
at rest using the Windows Data Protection API (DPAPI) and never stored
in plaintext in configuration files, logs, or stdout.

Contract
--------
- Only the Windows user who encrypted a secret can decrypt it (user-scope).
- The storage file is a JSON dictionary mapping secret names to base64-encoded
  DPAPI-encrypted blobs.
- Secret values are never written to logs, exception messages, or repr output.
- On non-Windows platforms all public functions raise ``NotImplementedError``.

Example
-------
    from harness.secrets.dpapi import encrypt_secret, decrypt_secret, list_secrets

    encrypt_secret("DEEPSEEK_API_KEY", "sk-...")
    print(list_secrets())          # ["DEEPSEEK_API_KEY"]
    value = decrypt_secret("DEEPSEEK_API_KEY")
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from harness._constants import DPAPI_FILE_NAME, STATE_DIR

# ---------------------------------------------------------------------------
# platform guard
# ---------------------------------------------------------------------------


def _require_windows() -> None:
    if sys.platform != "win32":
        raise NotImplementedError(
            "DPAPI is Windows-only in v0.1.0. Cross-platform keyring support is v1.x."
        )


# P1 audit fix (2026-05-27): the previous module-import-time `_require_windows()`
# call was removed.  It crashed `python -m harness <anything>` and ~76 test
# files at COLLECTION time on Linux/macOS — including the ubuntu-latest CI
# leg and every Linux-based Claude Code agent session.  Every public function
# below still calls `_require_windows()` before touching DPAPI, so real DPAPI
# usage on a non-Windows host still raises cleanly; the module just imports.
#
# The Windows-only ctypes bindings below are now conditionally defined so the
# bare `import` does not crash on POSIX (`from ctypes import wintypes` and
# `ctypes.windll.crypt32...` are both Windows-only).

# ---------------------------------------------------------------------------
# ctypes DPAPI bindings (Windows only)
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", wintypes.LPBYTE),
        ]


    _CryptProtectData = ctypes.windll.crypt32.CryptProtectData
    _CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),  # pDataIn
        wintypes.LPCWSTR,            # szDataDescr
        ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
        ctypes.c_void_p,             # pvReserved
        ctypes.c_void_p,             # pPromptStruct
        wintypes.DWORD,              # dwFlags
        ctypes.POINTER(_DATA_BLOB),  # pDataOut
    ]
    _CryptProtectData.restype = wintypes.BOOL

    _CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),  # pDataIn
        wintypes.LPWSTR,             # ppszDataDescr (NULL allowed)
        ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
        ctypes.c_void_p,             # pvReserved
        ctypes.c_void_p,             # pPromptStruct
        wintypes.DWORD,              # dwFlags
        ctypes.POINTER(_DATA_BLOB),  # pDataOut
    ]
    _CryptUnprotectData.restype = wintypes.BOOL


# ---------------------------------------------------------------------------
# low-level DPAPI helpers
# ---------------------------------------------------------------------------


def _dpapi_encrypt(plaintext: bytes) -> bytes:
    """Encrypt *plaintext* with DPAPI (user-scope). Return the ciphertext blob."""
    blob_in = _DATA_BLOB()
    blob_in.cbData = len(plaintext)
    buf_in = ctypes.create_string_buffer(plaintext)
    blob_in.pbData = ctypes.cast(buf_in, wintypes.LPBYTE)

    blob_out = _DATA_BLOB()

    ok = _CryptProtectData(
        ctypes.byref(blob_in),
        None,  # no description
        None,  # no entropy
        None,
        None,
        0,  # user-scope (CRYPTPROTECT_LOCAL_MACHINE UNSET)
        ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

    size = blob_out.cbData
    data = ctypes.string_at(blob_out.pbData, size)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return data


def _dpapi_decrypt(ciphertext: bytes) -> bytes:
    """Decrypt a DPAPI blob. Return the original plaintext bytes."""
    blob_in = _DATA_BLOB()
    blob_in.cbData = len(ciphertext)
    buf_in = ctypes.create_string_buffer(ciphertext)
    blob_in.pbData = ctypes.cast(buf_in, wintypes.LPBYTE)

    blob_out = _DATA_BLOB()

    ok = _CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

    size = blob_out.cbData
    data = ctypes.string_at(blob_out.pbData, size)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return data


# ---------------------------------------------------------------------------
# file I/O helpers
# ---------------------------------------------------------------------------


def _state_dir() -> Path:
    """Return the path to the state directory (created if missing).

    Uses the shared ``STATE_DIR`` from ``harness._constants`` (repo-root anchored)
    to avoid cwd-drift across modules (Wave 2A MED fix).
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def _secrets_path() -> Path:
    return _state_dir() / DPAPI_FILE_NAME


def _load_data() -> dict[str, str]:
    """Load the secrets JSON dict from disk. Returns empty dict if missing."""
    path = _secrets_path()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        from harness.errors import ConfigCorruption
        raise ConfigCorruption(
            "Corrupted secrets file: top-level value is not a JSON object",
            context={"file": str(path)},
        )
    return data


def _save_data(data: dict[str, str]) -> None:
    """Atomically write *data* to the secrets file with 0600 permissions."""
    path = _secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="._secrets_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise

    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def encrypt_secret(name: str, value: str) -> None:
    """Encrypt *value* under *name* and persist it to the DPAPI store.

    Args:
        name: The secret identifier (e.g. ``"DEEPSEEK_API_KEY"``).
        value: The plaintext secret value. This is never logged or stored
            in plaintext.

    Raises:
        NotImplementedError: On non-Windows platforms.
        ValueError: If *name* is empty.
        OSError: If DPAPI encryption or file I/O fails.
    """
    _require_windows()
    if not name:
        raise ValueError("Secret name must not be empty")
    # NEVER log *value*
    blob = _dpapi_encrypt(value.encode("utf-8"))
    data = _load_data()
    data[name] = base64.b64encode(blob).decode("ascii")
    _save_data(data)


def decrypt_secret(name: str) -> Optional[str]:
    """Return the decrypted value for *name*, or ``None`` if absent OR empty.

    Patch 2026-05-21: an EMPTY stored secret (b64 of empty plaintext) is now
    treated as missing — returns ``None`` instead of ``""``.  This closes
    the bug where ``has_secret`` reported True for stub entries while
    consumer code's ``if value:`` truthy-check correctly dropped the empty
    string, producing a confusing "SET but empty" state.

    Args:
        name: The secret identifier.

    Returns:
        The plaintext secret, or ``None`` if no such secret exists or it
        decrypts to an empty string.

    Raises:
        NotImplementedError: On non-Windows platforms.
        OSError: If DPAPI decryption fails.
    """
    _require_windows()
    data = _load_data()
    b64 = data.get(name)
    if b64 is None:
        return None
    blob = base64.b64decode(b64)
    plaintext = _dpapi_decrypt(blob)
    decoded = plaintext.decode("utf-8")
    if not decoded:  # treat empty-string secrets as missing
        return None
    return decoded


def delete_secret(name: str) -> None:
    """Remove *name* from the DPAPI store. Silent if not present.

    Args:
        name: The secret identifier.

    Raises:
        NotImplementedError: On non-Windows platforms.
    """
    _require_windows()
    data = _load_data()
    if name in data:
        del data[name]
        _save_data(data)


def rotate_secret(name: str, new_value: str, *,
                  keep_previous: bool = True) -> dict[str, object]:
    """W14-KEY-ROTATION 2026-05-28: atomically rotate a DPAPI secret.

    Reads the current value (if present), writes the new value, and
    optionally preserves the old value as ``<name>_PREVIOUS_<ts>`` so
    the operator has an emergency rollback window.

    Args:
        name: The secret identifier (e.g. ``"DEEPSEEK_API_KEY"``).
        new_value: The new plaintext secret.  Never logged.
        keep_previous: If True (default), store the previous value
            under ``<name>_PREVIOUS_<YYYYMMDDhhmmss>`` so the operator
            has a one-step rollback if the new key turns out broken.
            Set False for unrecoverable rotations (suspected key
            compromise — destroy the old key immediately).

    Returns:
        Dict describing the rotation:
            ``rotated``: the secret name
            ``previous_kept_as``: the backup secret name, or None
            ``timestamp_utc``: ISO timestamp of the rotation
            ``had_previous_value``: True iff the secret existed before
                rotation (False ⇒ first-time write disguised as rotate)

    Raises:
        NotImplementedError: On non-Windows platforms.
        ValueError: If *name* is empty OR *new_value* is empty.
        OSError: If DPAPI encryption fails.

    Security notes:
      - The new value never appears in logs, exceptions, or this dict.
      - The previous value is NOT returned (only the storage name).
      - Two-phase store: previous is written first, then new value.
        If the previous-store fails, rotation aborts before touching
        the live key (no half-state).
      - The audit ledger gets a separate ``key_rotation`` event via
        :func:`harness.audit_jsonl.append_key_rotation_event`.
    """
    _require_windows()
    if not name:
        raise ValueError("Secret name must not be empty")
    if not new_value:
        raise ValueError("New value must not be empty")

    from datetime import datetime as _dt, timezone as _tz

    ts = _dt.now(_tz.utc).strftime("%Y%m%d%H%M%S")

    # Read current value (None if first-time write).  Never logged.
    try:
        existing = decrypt_secret(name)
    except Exception:
        existing = None

    previous_kept_as: Optional[str] = None

    if existing is not None and keep_previous:
        # Two-phase: write the backup FIRST so a crash mid-rotation
        # leaves a recoverable state.
        previous_kept_as = f"{name}_PREVIOUS_{ts}"
        encrypt_secret(previous_kept_as, existing)

    # Now write the new value (overwrites existing).
    encrypt_secret(name, new_value)

    return {
        "rotated": name,
        "previous_kept_as": previous_kept_as,
        "timestamp_utc": _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "had_previous_value": existing is not None,
    }


def list_secrets() -> list[str]:
    """Return a list of secret **names** stored in the DPAPI file.

    This function explicitly NEVER returns secret values.

    Returns:
        List of secret identifiers.

    Raises:
        NotImplementedError: On non-Windows platforms.
    """
    _require_windows()
    data = _load_data()
    return list(data.keys())


def has_secret(name: str) -> bool:
    """Return ``True`` if a secret with *name* exists AND is non-empty.

    Patch 2026-05-21: an empty stored secret is treated as missing so
    that ``has_secret`` and ``decrypt_secret`` agree.  Operator tools
    (e.g. ``harness env --show-set``) should report ``SET`` only when
    a real value is present.

    Args:
        name: The secret identifier.

    Returns:
        Boolean indicating real presence (not just a stub entry).

    Raises:
        NotImplementedError: On non-Windows platforms.
    """
    _require_windows()
    if name not in _load_data():
        return False
    # Verify the secret decrypts to a non-empty value (empty-stub guard).
    try:
        return decrypt_secret(name) is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI helper (used by install wizard)
# ---------------------------------------------------------------------------


def _cli_set(name: str) -> None:
    """Read plaintext from stdin, encrypt under *name*, and persist."""
    import sys

    value = sys.stdin.read().rstrip("\n")
    if not value:
        sys.exit(2)  # blank input
    encrypt_secret(name, value)
    sys.stdout.write(f"{name}: SET\n")


# Alias for unified read interface (v2/A proxy)
read_secret = decrypt_secret


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "set":
        _cli_set(sys.argv[2])
        sys.exit(0)
    else:
        sys.stderr.write("Usage: python -m harness.secrets.dpapi set <NAME>\n")
        sys.exit(2)
