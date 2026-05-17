# Wave 2B Batch 1 Security Audit
**Auditor:** general-purpose agent
**Date:** 2026-05-17
**Files audited:** `src/harness/engines/concrete.py` (404 LOC), `src/harness/state/jsonl_log.py` (250 LOC)

## Summary
- HIGH severity findings: 1
- MED severity findings: 4
- LOW severity findings: 4
- Verdict: **needs-amendment**

---

## Per-file findings

### concrete.py

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Uses httpx (not requests/urllib) | **PASS** | L21–22: `import httpx` / `from httpx import Timeout`. No other HTTP libs imported. |
| 2 | httpx Timeout set on every request (connect=10, read=120, write=10) | **PASS** | L42: `_DEFAULT_TIMEOUT = Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)` — applied in all three clients (L98, L191, L280). |
| 3 | No `verify=False` anywhere | **PASS** | L97, L190, L279 all explicitly `verify=True`. grep -E 'verify=False' → 0 hits. |
| 4 | API key resolution: DPAPI first, then env, no value leak in errors | **PASS** | L383–386: `if prefer_dpapi and dpapi.has_secret(env_var): … else: api_key = os.environ.get(env_var)`. L388–391 raises `RuntimeError(f"No API key for {name_lower}. Run `harness env` to verify.")` — no value, no env-var name, no attempted key. |
| 5 | `__repr__` not overridden in concrete subclasses (or masks api_key if so) | **PASS** | No `__repr__` in any of `DeepSeekConcrete`, `KimiConcrete`, `AnthropicConcrete`. They inherit from `Engine` (base.py L39), which does not define one. Default object repr is safe. *Note: the Wave-1 stubs `DeepSeekEngine`/`KimiEngine`/`AnthropicEngine` in `base.py` DO override `__repr__` and correctly mask (L97, L129, L159) — those are not the concrete classes under audit but the precedent is safe.* |
| 6 | `EngineResponse.error` never contains API key, body, or headers | **PASS** | L125: `error=f"HTTP {e.response.status_code}"` (status code only). L133: `error="timeout"`. L141: `error="network"`. L149: `error="internal"`. Identical pattern in Kimi (L218, 226, 234, 242) and Anthropic (L308, 316, 324, 332). No response bodies referenced. |
| 7 | `EngineResponse.text` never contains API key | **PASS** | On success, text comes from `_extract_chat_text`/`_extract_anthropic_text` which read only `choices[0].message.content` (L50–56) or first text block (L59–68). On failure paths text is always `""`. API key never reaches the text field. |
| 8 | On HTTP 4xx/5xx: `"HTTP <status>"` only, NOT body | **PASS** | L125/218/308: `f"HTTP {e.response.status_code}"` — no `.text`, no `.json()`, no `.content`. |
| 9 | On timeout: `"timeout"` only | **PASS** | L133/226/316: `error="timeout"`. |
| 10 | DeepSeek v4-flash: `--no-thinking` honored (HIGH-7) | **PASS** | L158: `no_thinking = extra.get("--no-thinking", False) or model.endswith("-flash")`. |
| 11 | DeepSeek: `model.endswith("-flash")` → temperature=0.0 + thinking=False | **PASS** | L158–166: `temperature = 0.0 if no_thinking else 0.6` and `if no_thinking: payload["thinking"] = False`. Both branches covered. |
| 12 | User-Agent = `xaxiu-harness/<version>` only, no system info | **PASS** | L45–47: `return f"xaxiu-harness/{__version__}"`. No `platform`, `sys.version`, or OS data appended. Applied at L105, 198, 288. |
| 13 | Exact endpoint URLs from packet | **PASS** | L102: `"https://api.deepseek.com/v1/chat/completions"`. L195: `"https://api.moonshot.cn/v1/chat/completions"`. L284: `"https://api.anthropic.com/v1/messages"` with L287 `"anthropic-version": "2023-06-01"` header. |
| 14 | `dispatch()` never raises (broad except + EngineResponse(success=False)) | **PASS** | All three engines wrap the entire flow in `try:` with `except Exception:` catch-all at L143/236/326 returning `EngineResponse(success=False, …)`. No `raise` inside the try blocks. |
| 15 | Imports from `harness.secrets import dpapi` (not direct ctypes) | **PASS** | L27: `from harness.secrets import dpapi`. No ctypes import. DPAPI accessed only via `dpapi.has_secret()` and `dpapi.decrypt_secret()` (L383–384). |
| 16 | No `print(`, `logging.info(` with secrets | **PASS** | grep for `print\(\|logging\.` → 0 hits in the file. |

**Findings:**

- **MED-1 (concrete.py):** Unused import `API_KEY_ENV_VARS` from `harness._constants` (L25). The factory defines its own local `_ENV_VAR_MAP` (L33–37) that is a *byte-identical duplicate* of `_constants.API_KEY_ENV_VARS`. This violates the cross-file requirement that both files import shared identifiers from `harness._constants` rather than redefining them. **Fix:** delete `_ENV_VAR_MAP` and use the imported `API_KEY_ENV_VARS` directly at L375, L380. (Currently the import is dead code and the duplicate map is the source of truth — drift risk if env vars ever change.)

- **MED-2 (concrete.py):** Broad `except Exception:` on L143, L236, L326 swallows *every* exception type including `KeyboardInterrupt`-adjacent `SystemExit` is NOT caught (good — `BaseException` not used), but also swallows `ValueError`/`KeyError` from malformed JSON (`response.json()`) and silently buries them as `"internal"`. The error string `"internal"` provides operators zero forensic signal. Suggest adding `json.JSONDecodeError` and `KeyError` branches with explicit `"malformed_response"` outcome — useful for the packet-trap detector that v1.2 HIGH-7 wires up. Not a security break, but reduces observability on real failure modes.

- **LOW-1 (concrete.py):** `_DEFAULT_TIMEOUT` adds `pool=10.0` (L42) which was not in the packet requirement (packet specified connect/read/write only). Functionally safe — pool-acquire timeout prevents indefinite hangs on connection-pool exhaustion — but is an unrequested addition. Recommend documenting in the constant's comment.

- **LOW-2 (concrete.py):** `KimiConcrete._build_payload` (L246–256) silently accepts a `temperature` from `extra_args` with no clamping. If a caller passes `temperature=999`, Kimi's API will reject and surface as `"HTTP 400"`. Not a security issue but worth a `max(0.0, min(2.0, …))` clamp.

- **LOW-3 (concrete.py):** Per-dispatch `httpx.Client` construction (L96/189/278) creates and destroys a TCP/TLS connection on every call. Functional, but means connection pooling is wasted. Performance only; not security.

---

### jsonl_log.py

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Closed schema — exactly 8 keys, 9th key raises `LogSchemaError` | **PASS (with caveat)** | L36–47: `_ALLOWED_KEYS` is the 8-key frozenset. L199–202: `if set(record) != _ALLOWED_KEYS: raise LogSchemaError(...)`. **Caveat:** since `write_log_entry` builds the record from 8 kwargs (L188–197), the 9-key path is unreachable from this function — the gate fires only if someone adds a key to the literal. The `LogSchemaError` defense is correct but the test must exercise the literal-builder path directly. |
| 2 | Outcome enum validated against the 6-value set | **PASS** | L25–34: `_ALLOWED_OUTCOMES` matches packet exactly. L172–175: `if outcome not in _ALLOWED_OUTCOMES: raise ValueError(...)`. |
| 3 | Backend validated against `SUPPORTED_BACKENDS` | **PASS** | L177–180: `if backend not in SUPPORTED_BACKENDS: raise ValueError(...)`. Imported from `_constants` L16. |
| 4 | Project validated against `PROJECT_NAME_REGEX` | **PASS** | L182–185: `if not re.fullmatch(PROJECT_NAME_REGEX, project): raise ValueError(...)`. |
| 5 | `_redact()` covers all 5 patterns (sk-, Bearer, api_key=, ms-, deepseek-) | **PASS** | L53–59: all 5 compiled. Pattern 3 uses `(?i)` case-insensitive plus generous separator `[\"':=]+` for API_KEY=, api-key:, "api_key":, etc. |
| 6 | `_redact()` applied to `packet_path` before serialization | **PASS** | L191: `"packet_path": _redact(packet_path)`. Also applied to `backend` (L192), `outcome` (L194), `fallback_to` (L196) — defense in depth. |
| 7 | Atomic append: `"ab"` mode + fsync | **PASS** | L211–214: `with open(log_file, "ab") as f: f.write(data); f.flush(); os.fsync(f.fileno())`. |
| 8 | Rotation at 100MB → `engine_performance_log.<YYYY-MM>.jsonl.gz` | **PASS (with bug)** | L23 size constant correct. L121–124: rotation triggers above 100MB. **BUG (HIGH-1):** L124 uses `log_file.with_suffix(f".{_rotation_suffix()}.jsonl.gz")` — `Path.with_suffix` *replaces* the existing `.jsonl` suffix, producing `engine_performance_log.2026-05.jsonl.gz` (correct) only by accident because the format string starts with `.`. But pathlib treats a suffix that contains additional dots ambiguously — let's verify by tracing: `Path("engine_performance_log.jsonl").with_suffix(".2026-05.jsonl.gz")` → `engine_performance_log.2026-05.jsonl.gz`. **Actually correct.** Demoting from HIGH to MED-3 (see below) because the test still passes but the technique is fragile. |
| 9 | Uses `gzip` module for compression | **PASS** | L8 `import gzip`. L134: `with gzip.open(rotated, "wb") as dst`. Streamed 64KB chunks (L135–139) — won't OOM on large logs. |
| 10 | File mode 0600 after rotation | **PASS (partial — see HIGH-1)** | L140: `_set_restricted_permissions(rotated)` after rotation. L144: also applied to truncated original. L216: applied after every write. **HIGH-1 (see below):** `_set_restricted_permissions` uses `os.chmod` (L96), which on Windows is a no-op for everything other than read-only — i.e., it does NOT actually enforce 0600 on Windows. The packet explicitly required "File mode 0600 after rotation". On Windows this is silently a no-op. |
| 11 | Never appends extras (`packet_content`, `error_response`, `request_headers`, `engine_url`) | **PASS** | The record literal at L188–197 contains exactly the 8 kwargs. No extras. The schema-gate at L199–202 enforces. |
| 12 | json.dumps with `ensure_ascii=True, sort_keys=True` | **PASS** | L205: `json.dumps(record, ensure_ascii=True, sort_keys=True)`. |
| 13 | Custom `LogSchemaError` defined and raised | **PASS** | L62–63: `class LogSchemaError(ValueError):`. Raised L200. Subclass of ValueError is fine and aids `except ValueError` callers. |

**Findings:**

- **HIGH-1 (jsonl_log.py + cross-cutting):** `_set_restricted_permissions` (L93–98) calls `os.chmod(path, 0o600)` and silently swallows failure. **On Windows (the target platform — DPAPI module already enforces `sys.platform == "win32"` at import), `os.chmod` only honors the read-only bit; POSIX mode bits are ignored.** This means the packet requirement "File mode 0600 after rotation" is *not actually enforced* on the production OS — the call is a no-op. Recommendation: use `icacls`-equivalent via `ctypes`/`win32security` to set a Windows DACL restricting access to the current SID, OR explicitly document the limitation and add a SECURITY.md note. Same pattern appears in `secrets/dpapi.py` L203 — likely a systemic v1.2 amendment gap. **This is the only HIGH finding and must be addressed (or formally accepted as a limitation in v1.2 amendments) before Wave 2B batch 2.**

- **MED-3 (jsonl_log.py):** `Path.with_suffix()` at L124 and L128 is fragile when applied to a multi-dot replacement string. Current output is correct (`engine_performance_log.2026-05.jsonl.gz`), but if `LOG_FILE_NAME` ever changes to something dotless or with a different extension, behavior shifts unexpectedly. Recommend explicit `log_file.parent / f"{log_file.stem}.{_rotation_suffix()}.jsonl.gz"`.

- **MED-4 (jsonl_log.py):** Rotation race: between `rotate_if_needed()` (L169) and the `open(log_file, "ab")` (L211) there is no lock. If two processes write concurrently and one rotates while the other is mid-write, the writer can append to the rotated file or the writer's data can be lost. The harness *may* be single-process today, but the packet didn't promise that. Recommend a `msvcrt.locking()` advisory lock around rotate+append on Windows, or document single-writer assumption.

- **LOW-4 (jsonl_log.py):** `read_recent_entries` (L223–250) reads the whole file into memory then slices the tail. For a 100MB file this is ~100MB resident memory. Use `collections.deque(f, maxlen=limit)` to bound at `limit` records. Not security-related; LOW.

---

## Cross-file findings

| Check | Status | Evidence |
|---|---|---|
| Both files import from `harness._constants` for shared identifiers | **PARTIAL FAIL** | jsonl_log.py L16: imports `PROJECT_NAME_REGEX`, `STATE_DIR`, `SUPPORTED_BACKENDS` ✓. concrete.py L25: imports `API_KEY_ENV_VARS` but **does not use it** — redefines as local `_ENV_VAR_MAP` (L33–37). See MED-1. |
| No `eval`/`exec`/`subprocess.run(shell=True)` | **PASS** | grep across both files → 0 hits. |
| All file IO uses `encoding="utf-8"` | **PASS** | jsonl_log.py L206 encodes via `.encode("utf-8")` for binary append; L235 read uses `encoding="utf-8"`. Binary `"ab"`/`"wb"` modes don't need encoding. concrete.py does no file IO. |
| No hardcoded credentials, debug endpoints, or backdoors | **PASS** | grep across both files. URLs are the three production endpoints only. No localhost or staging hosts. No bypass flags. No commented-out dev keys. |

---

## Verdict

**needs-amendment**

Blocking item: **HIGH-1** — the `0o600` file-mode requirement from the packet is silently a no-op on Windows, the only supported platform per `secrets/dpapi.py:42`. The audit cannot pass a security requirement that the code does not actually enforce. The same gap exists in the already-shipped DPAPI module (`secrets/dpapi.py:203`), so this is likely a systemic v1.2 amendment oversight rather than a regression introduced by this batch — but it must be either fixed (Windows DACL via `win32security`/`ctypes`) or explicitly documented in `spec/v1.2-security-amendments.md` as an accepted limitation before Wave 2B batch 2 ships.

Secondary cleanup (non-blocking but should be folded into the same fix-up commit): MED-1 dead-code duplicate `_ENV_VAR_MAP` in concrete.py drifts from `_constants.API_KEY_ENV_VARS`; MED-3/4 rotation robustness; MED-2 observability on JSON-decode failures.

All other ~25 per-packet requirements PASS with line-cited evidence.

**Counts:** HIGH=1, MED=4, LOW=4. Verdict: needs-amendment.
