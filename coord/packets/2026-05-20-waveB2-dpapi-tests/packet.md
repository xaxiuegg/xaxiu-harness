# Packet: Wave B/2.dpapi — boundary tests for secrets/dpapi.py

## Mission

Push `src/harness/secrets/dpapi.py` coverage from 32% to >60%. Module is Windows-only (DPAPI ctypes); mock the crypt32 calls so tests run cross-platform.

## In-scope (NEW file only)

`tests/test_secrets_dpapi.py` — single new test file. NO modifications to `src/harness/secrets/dpapi.py` (other waves may be reading it).

## Required test coverage

Read `src/harness/secrets/dpapi.py` for the function list. Cover at minimum:

1. **`encrypt_secret` / `decrypt_secret` roundtrip** — patch `_dpapi_encrypt` and `_dpapi_decrypt` to identity (return input bytes unchanged) so the roundtrip is testable without real DPAPI. Verify the JSON store after encrypt has the name → base64 mapping; verify decrypt returns the original plaintext bytes.
2. **`encrypt_secret("")` empty name** → raises `ValueError`.
3. **`list_secrets()`** — returns only NAMES, never values. After encrypting two keys, list returns both names; no plaintext anywhere in the result.
4. **`has_secret("X")` true/false** — returns True after encrypt, False before/after delete.
5. **`delete_secret("X")`** — removes the entry; subsequent `decrypt_secret` returns None.
6. **`_load_data` corrupted file** — write `[1, 2, 3]` (a JSON array, not object) to the secrets file path; `_load_data` raises `ConfigCorruption` (per Wave A.6 retrofit).
7. **`_save_data` atomicity** — verify tempfile is used (mock `tempfile.mkstemp` to return a known path; verify `os.replace` is called).
8. **`_cli_set` from stdin** — call `python -m harness.secrets.dpapi set TEST_KEY` via `subprocess.run` with stdin="value\n"; verify exit 0 + "TEST_KEY: SET" on stdout. (Or mock `sys.stdin.read` directly.)
9. **`_cli_set` blank stdin** → exits 2.

Use `pytest` fixtures + `unittest.mock.patch`. Skip tests that need real Windows (mark `@pytest.mark.skipif(sys.platform != "win32", ...)`) — but most tests should NOT need real Windows because the DPAPI calls are mocked.

## Acceptance criteria

1. `python -m pytest tests/ -q` shows ≥185 + new tests, all green.
2. `python -m pytest tests/test_secrets_dpapi.py --cov=src/harness/secrets/dpapi --cov-report=term-missing` shows >60% coverage.
3. No modifications to any file outside `tests/test_secrets_dpapi.py`.
4. Tests NEVER print or assert on real plaintext secret values (use mocks).
5. Single commit: `test(secrets/dpapi): boundary tests (Wave B/2.dpapi)`.

## Reference

- `src/harness/secrets/dpapi.py` — what's being tested (read first)
- `src/harness/errors.py::ConfigCorruption` — raised by corrupted-file path
- `tests/test_install_smoke.py` — pattern for patching `harness.secrets.dpapi.has_secret`

## Output format

Single new file at `tests/test_secrets_dpapi.py`. No modifications elsewhere.
