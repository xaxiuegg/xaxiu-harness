# Packet: Wave 2A / DPAPI secrets helper

## Mission
Produce `src/harness/secrets/dpapi.py` — Windows DPAPI-based secret storage helper. Implements v1.2 amendment HIGH-8 (API keys MUST be DPAPI-encrypted at rest, never plaintext in config files).

## Required API

```python
def encrypt_secret(name: str, value: str) -> None: ...
def decrypt_secret(name: str) -> Optional[str]: ...
def delete_secret(name: str) -> None: ...
def list_secrets() -> list[str]: ...  # returns NAMES only, never values
def has_secret(name: str) -> bool: ...
```

## Storage layout
- File: `<repo_root>/state/secrets.dpapi` (use `DPAPI_FILE_NAME` from `src/harness/_constants.py`)
- Format: JSON dict `{name: base64(encrypted_blob)}`. JSON not pickle (deserialization safety).
- File mode: 0600 (user-only). Use `os.chmod` on the file after each write.
- Encryption scope: user-scope (CRYPTPROTECT_LOCAL_MACHINE flag UNSET) — only the encrypting user can decrypt.

## Implementation
- Use `ctypes` to call `CryptProtectData` and `CryptUnprotectData` from `crypt32.dll`. NO pywin32 dependency.
- Encrypt: UTF-8 bytes → DPAPI blob → base64 string for JSON storage.
- Decrypt: reverse. Return UTF-8 string on success, None if name absent.
- Atomic file writes: write to tempfile in same dir, fsync, `os.replace`.
- `list_secrets()` reads the JSON dict and returns `list(data.keys())` — explicitly NEVER values.
- `delete_secret(name)`: remove key from dict, atomic write back. Silent if not present.
- `has_secret(name)`: returns `name in data` — bool only, no value disclosure.

## CRITICAL security requirements (NON-NEGOTIABLE)
1. NEVER log secret values. Not in exceptions, not in __repr__ output, not in error messages.
2. Exception messages may include the SECRET NAME but NEVER the value or encrypted blob.
3. `list_secrets()` returns names only. Document this explicitly in the docstring.
4. All file IO with explicit `encoding="utf-8"`.
5. File mode 0600 enforced after each write.
6. On non-Windows: raise `NotImplementedError("DPAPI is Windows-only in v0.1.0. Cross-platform keyring support is v1.x.")` from ALL public functions.
7. Detect platform via `sys.platform == "win32"`; check at module import time and at each public function entry.
8. NO module-level state holding decrypted values. Decrypt on-demand, return, garbage collect.

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/secrets/dpapi.py`. Target 150-250 lines. Type-hint everything. Imports: stdlib only (`ctypes`, `json`, `os`, `pathlib`, `sys`, `base64`, `tempfile`, `typing`) + local `from harness._constants import DPAPI_FILE_NAME`. NO pywin32.

Include module docstring explaining: the contract, the Windows-only constraint, the user-scope encryption rationale, and an example usage pattern.

## Reference
- v1.2 amendment HIGH-8 at `D:/Projects/xaxiu-harness/spec/v1.2-security-amendments.md` (the authoritative fix language)
- `src/harness/_constants.py` for `DPAPI_FILE_NAME`
- Windows DPAPI MSDN docs (CryptProtectData/CryptUnprotectData) are the API reference
