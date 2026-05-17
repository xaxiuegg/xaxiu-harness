# Wave 2A Deliverables Security Audit
**Auditor:** general-purpose agent
**Date:** 2026-05-17
**Files audited:** `_constants.py` (28 LOC, Claude), `dpapi.py` (303 LOC, Kimi), `loader.py` (230 LOC, Kimi), `files.py` (332 LOC, Kimi), `db.py` (376 LOC, DeepSeek)

## Summary
- HIGH severity findings: **2**
- MED severity findings: **4**
- LOW severity findings: **5**
- Files clean: `_constants.py` (no findings)
- Files with HIGH findings: `files.py` (1), `db.py` (1)

## Per-file findings

### _constants.py — CLEAN (PASS)
- No secrets, no suspicious URLs, no debug endpoints.
- Cross-cutting v1.2 values match spec: `DASHBOARD_PORT=7878` (MED-1), `DASHBOARD_BIND_ADDRESS="127.0.0.1"` (HIGH-1), `DPAPI_FILE_NAME="secrets.dpapi"` (HIGH-8), `LIMIT_MAX=1000` (HIGH-11), `PROJECT_NAME_REGEX=r"^[a-z0-9-]{1,32}$"` (HIGH-11 §4.1).
- `SUPPORTED_BACKENDS` and `API_KEY_ENV_VARS` correctly cover the three backends. No `anthropic` token-confusion.
- Module is import-side-effect-free, no module-level mutable state.
- No findings.

---

### dpapi.py — PASS WITH MINOR FINDINGS

Per-requirement scorecard (9 requirements):
- **Windows-only via `sys.platform == "win32"`** at every public function entry: PASS — `_require_windows()` called at top of `encrypt_secret` (L222), `decrypt_secret` (L245), `delete_secret` (L264), `list_secrets` (L282), `has_secret` (L301), AND at module-import time (L48).
- **`ctypes` calling `crypt32.dll`, NOT pywin32**: PASS — `ctypes.windll.crypt32.CryptProtectData` (L65), `CryptUnprotectData` (L77). No `import win32*`. Stdlib-only import list (`ctypes, json, os, sys, base64, tempfile, pathlib, typing`) matches packet allow-list exactly.
- **User-scope (NO `CRYPTPROTECT_LOCAL_MACHINE` flag)**: PASS — `dwFlags=0` passed at L110 with comment `# user-scope (CRYPTPROTECT_LOCAL_MACHINE UNSET)`. No `CRYPTPROTECT_*` constants set anywhere.
- **`list_secrets()` returns NAMES only**: PASS — L284 `return list(data.keys())`. Docstring at L271-281 explicitly states "explicitly NEVER returns secret values."
- **Atomic file writes (tempfile + os.replace)**: PASS — `_save_data` (L178-201) opens via `tempfile.mkstemp(dir=path.parent, prefix="._secrets_")`, writes, `f.flush()` + `os.fsync(fd)`, `os.replace(tmp, path)`. Cleanup-on-error path at L190-199 unlinks temp.
- **File mode 0600 set after every write**: PASS — L201 `os.chmod(path, 0o600)` after `os.replace`. Single write code path so all writes covered.
- **NEVER logs values, never in exceptions**: PASS — `encrypt_secret` body never references `value` in any string/exception (L209-229). Decrypt-on-demand pattern; no value leaks into ValueError or OSError messages. WinError from L114, L141 returns Windows error code, not plaintext.
- **No module-level state holding decrypted plaintext**: PASS — `_load_data()` reads JSON dict (ciphertext only) into local variable, never assigned to module-level. `decrypt_secret` decrypts to local `plaintext`, returns, garbage-collected.
- **JSON storage, not pickle**: PASS — `json.dump` (L186), `json.load` (L172). No `pickle`/`marshal` import.

Cross-cutting: No `os.system`, `subprocess`, `exec`, `eval`. No `os.environ[...]` subscript. All imports stdlib-only.

Findings:
- **LOW-W2A-1** `dpapi.py:157` — `_state_dir()` resolves to `Path.cwd() / "state"`, not `<repo_root>/state` as the packet specifies. CWD-relative state means running `harness` from a non-repo directory creates a parallel secrets store. Recommend `Path(__file__).resolve().parents[3] / "state"` (same as `files.py:48`) for canonical resolution. Same drift exists in `db.py:141` — see below.
- **LOW-W2A-2** `dpapi.py:54-55` — `import ctypes` / `from ctypes import wintypes` placed **after** `_require_windows()` import-time check (L48). On non-Windows the NotImplementedError fires before ctypes imports, so this works, but mixing imports below module-level executable code violates PEP 8 import ordering and could surprise static analyzers. Move ctypes imports inside the platform-guarded block or to the top of the file with `if sys.platform == "win32":` wrapping.
- **LOW-W2A-3** `dpapi.py:46-48` — Module-import-time `_require_windows()` raises `NotImplementedError` on non-Windows. This is correct behavior, but it means any cross-platform test harness that merely *imports* `harness.secrets.dpapi` (e.g., for symbol introspection on a Linux CI runner) will fail. The packet allows this trade-off ("at module import time and at each public function entry"), so this is documenting behavior rather than flagging it.

Verdict: **PASS** — implementation matches the v1.2 HIGH-8 amendment and packet contract exactly. No HIGH/MED findings.

---

### loader.py — PASS WITH MED FINDING

Per-requirement scorecard:
- **`yaml.safe_load` exclusively**: PASS — L189 (`yaml.safe_load(yaml_text)` in `load_template`) and L228 (`schema.load_adapter` which uses `yaml.safe_load` per Wave 1 audit). The CI guard comment is present at L5 (`# CI guard: ! grep -rn 'yaml\.load(' src/`). No `yaml.load(`, `yaml.unsafe_load`, or `yaml.FullLoader` anywhere.
- **Template name whitelist (exact 5)**: PASS — `ALLOWED_TEMPLATES` (L39-47) holds exactly `warehouse-style`, `generic-coding`, `writing-content`, `research-comparison`, `solo-dev`. `load_template` enforces via `if name not in ALLOWED_TEMPLATES: raise ValueError(...)` (L174-177).
- **project_root absolute + exists + is_dir + not under system dirs**: PASS — `_validate_project_root` (L66-99) chains `is_absolute()` (L74-75), `resolve(strict=True)` (L78), `is_dir()` (L84-85), and forbidden-prefix check (L88-97) using `Path.is_relative_to`. `_FORBIDDEN_PREFIXES` (L53-57) reads `WINDIR`, `PROGRAMFILES`, `PROGRAMDATA` from env with safe defaults via `os.environ.get` (not `[]` subscript).
- **csv_path / markdown path descendant of project_root**: PASS — `_validate_status_path` (L102-128) resolves `(root / rel_path).resolve()` then checks `is_relative_to(root_resolved)`. Try/except guard handles cross-drive `is_relative_to` ValueError defensively.
- **Validation errors ValueError with field name only, never file contents**: PASS — every error message is a fixed string with field name (e.g., L121 `f"{field_name} must be a string"`, L75 `"project_root must be an absolute path"`). No raw YAML text or file content interpolated. The one exception-chain pass-through at L81 (`f"...{exc}"`) wraps an `OSError`/`RuntimeError` from `resolve(strict=True)`, which contains the path but never file *contents*.
- **No eval/exec/subprocess**: PASS — none.

Cross-cutting: No `os.environ[...]` subscript (`os.environ.get` only at L54-56). Imports stdlib + yaml + relative `.schema` only.

Findings:
- **MED-W2A-1** `loader.py:50` — `_PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")` is a **second source of truth** for a project-name validation regex while `_constants.PROJECT_NAME_REGEX` defines `r"^[a-z0-9-]{1,32}$"`. This is exactly the duplicate-source-of-truth drift the `_constants.py` module exists to prevent (per v1.2 §3 and `_constants.py` docstring). The packet specifies this exact regex for `load_project_adapter` (lower/upper/underscores, 64 char limit), and the db.py regex is for SQLite-stored values (lower only, 32 char limit) — so the two regexes legitimately diverge — but a project that passes filesystem validation (e.g. `MyProj_v2`) will be **rejected by db.py** at first persistence, causing a confusing late failure. Recommend either (a) add `LOADER_PROJECT_NAME_REGEX` to `_constants.py` so both regexes live in one file, OR (b) document the divergence explicitly with a comment at both call sites.
- **LOW-W2A-4** `loader.py:88-94` — The forbidden-prefix check normalizes paths via `Path(forbidden_str).resolve()` and uses `Path.is_relative_to`. On Windows, `is_relative_to` is **case-sensitive** by default (`Path("C:/Windows/foo").is_relative_to(Path("C:/windows"))` returns False on Python < 3.12 / depending on filesystem). An attacker could potentially provide `project_root = "c:\\windows\\system32\\malicious"` and bypass the check. Recommend lowercasing both sides before comparison: `resolved_lower = Path(str(resolved).lower())` etc., OR `if str(forbidden).lower() in str(resolved).lower(): ...` as a defense-in-depth check. The docstring at L87 (`# Case-insensitive check on Windows`) **claims** case-insensitivity but the code does not implement it.

Verdict: **PASS** — all v1.2 HIGH-7 / MED-2 / MED-3 / LOW-5 requirements met. MED-W2A-1 is hygiene, LOW-W2A-4 is defense-in-depth.

---

### files.py — FAIL (1 HIGH, 1 MED, 1 LOW)

Per-requirement scorecard:
- **`yaml.safe_load` for harness.config.yml**: PASS — L205 `yaml.safe_load(fh)`. Write path uses `yaml.safe_dump` (L178). No `yaml.load(`, `yaml.unsafe_load`, or `yaml.FullLoader`.
- **JSON files use `json.load` / `json.dump`**: PASS — L234, L271, L301 (all reads); L157 (write). No `eval` parsing.
- **All writes atomic (tempfile + fsync + os.replace)**: PASS — `_atomic_write_json` (L150-168) and `_atomic_write_yaml` (L171-189) both use `tempfile.mkstemp` → `os.fsync(fd)` → `os.replace`. Cleanup on exception unlinks temp.
- **File mode 0600 after every write**: PARTIAL — `os.chmod(path, 0o600)` correctly called on POSIX (L147), but Windows path (L120-145) calls `_set_mode_0600` which uses pywin32 — see HIGH-W2A-1.
- **Parse errors raise `StateFileCorruptError` with path ONLY**: PASS — `StateFileCorruptError.__init__` (L39-42) builds `f"State file is corrupt: {path}"`. Every call site (L207, L213, L236, L238, L242, L273, L275, L279, L303, L305, L312) passes only the path; the original `yaml.YAMLError` / `json.JSONDecodeError` is chained via `from exc` but never interpolated into the message. The chained exception's `__str__` may still surface YAML/JSON detail when the exception propagates uncaught — but the message text itself contains no file content. PASS, with awareness that callers should not echo `exc.__cause__` to logs.
- **Pydantic models have `extra: "forbid"`**: PASS — `HarnessConfig.model_config` (L65), `ActiveDispatch.model_config` (L78), `LoopEntry.model_config` (L87), `EngineHealth.model_config` (L104). All four models forbid extra fields.
- **Missing files handled gracefully**: PASS — `read_harness_config` returns `HarnessConfig(harness_version="1.2.0")` default (L201-202); `read_active_dispatches` returns `[]` (L230-231); `read_loops` returns `[]` (L267-268); `read_engine_health` returns `{}` (L297-298). None raise on missing.
- **LoopEntry.command validator**: PASS — L91-94 enforces `command.startswith("harness ")`.

Findings:
- **HIGH-W2A-1** `files.py:118-145` — **Unrequested pywin32 import + dependency violation + functionally weak DACL.** The Wave 2A state-files packet (line 81) explicitly limits imports to "stdlib (`json`, `os`, `pathlib`, `tempfile`, `typing`) + `yaml` + `pydantic` + `from harness._constants import ...`". `pywin32` is not in the allow-list and is **not declared in `pyproject.toml`** (verified — `pyproject.toml` lists only click/pydantic/pyyaml/fastapi/uvicorn/httpx/websockets/rich; no `pywin32` / `pypiwin32` / `pywin32-ctypes`). This is parallel to the `_constants.py` `DASHBOARD_TOKEN_FILE` ACL requirement, but the packet's intent ("set file mode 0600 via `os.chmod` after replace") was to use **POSIX semantics** with `os.chmod` on Windows accepting that DPAPI user-scope encryption + NTFS default user-profile ACL inheritance is the deeper security boundary. Three sub-problems:
  - **(a) Undeclared runtime dependency.** Any clean install will `ImportError: No module named 'win32security'` on the very first state-file write on Windows. Wave 2B+ will hit this immediately.
  - **(b) Engine added unrequested code.** The packet did not ask for an ACL implementation; Kimi gold-plated. The 25-line Windows branch is not just out-of-scope — it's buggy (see (c)).
  - **(c) The DACL is functionally broken.** The code at L131-145 builds an ACL with a *single* AddAccessAllowedAce for the current user, then calls `SetSecurityDescriptorDacl(1, dacl, 0)`. There is **no explicit deny-everyone-else ACE**, no `SetSecurityDescriptorOwner` call, and no flag to disable inheritance. The result preserves any inherited ACEs from the parent directory (which on a default Windows user profile may grant SYSTEM and Administrators read access — both legitimately permitted to read the user's profile). The header comment "denies everyone else" is *aspirational, not implemented*. Real "deny everyone else" requires either (i) `dacl.AddAccessDeniedAce(...)` for the Everyone SID, OR (ii) `SetSecurityDescriptorControl(SE_DACL_PROTECTED, SE_DACL_PROTECTED)` to break inheritance plus a complete owner+user-only DACL. Neither is done.

  **Remediation:** delete L118-145 and use `os.chmod(path, 0o600)` unconditionally. Windows accepts `os.chmod` and translates it to a NTFS-mode-bit best-effort (it's a no-op for group/other bits but sets read-only). The packet explicitly accepted this trade-off. If genuine ACL hardening is wanted, it belongs in a separate `secrets/acl.py` module with proper deny-Everyone semantics and `pywin32` declared as a Windows-only dependency in pyproject.toml.

- **MED-W2A-2** `files.py:48` — `STATE_DIR = Path(__file__).resolve().parents[3] / "state"`. Compared with `dpapi.py:157` (`Path.cwd() / "state"`) and `db.py:141` (`Path.cwd() / "state" / DB_FILE_NAME`), this is the **third state-dir resolution convention** in the wave. The packet allowed either, but the inconsistency means a user who runs `cd /tmp && harness ...` will get DPAPI secrets and SQLite DB in `/tmp/state/` while pydantic state lives in `<repo>/state/`. State will desync. Recommend adding `STATE_DIR` to `_constants.py` (or a dedicated `state/__init__.py`) and using it everywhere.

- **LOW-W2A-5** `files.py:118` — `import sys` inside `_set_mode_0600`. Functionally harmless (Python caches the import) but stylistically should be hoisted to the module-level import block. Likely a holdover from the Windows branch that should not exist at all.

Verdict: **FAIL — needs amendment** before Wave 2B can build on top. The pywin32 import is a build-breaker the moment a clean install happens.

---

### db.py — PASS WITH 2 MED FINDINGS

Per-requirement scorecard:
- **ALL queries parameterised, NO f-string/%/+ in SQL**: PARTIAL — every `cursor.execute` call uses `?` placeholders with tuple binding: `insert_dispatch` L190-194, `update_dispatch_status` L206-213, `insert_fallback` L224-228, `insert_observer_cycle` L241-245, `insert_status_write` L257-261, `insert_routing_change` L277-281, `query_active_dispatches` L305-318, `query_fallback_chain` L346-351, `query_routing_history` L362-375. **However**, `query_recent_events` L329 declares `sql = f"""..."""` — the f-string has no `{}` interpolations (verified — only static SQL inside), so there is no actual injection vector. BUT it WILL trip the CI guard suggested in the sqlite packet (line 83): `! grep -rnE 'execute\(["'"'"']\s*[A-Z]+.*\+' src/` won't catch this specific form, but a strict guard like `! grep -rn 'f"""\s*SELECT\|f"""\s*INSERT\|f".*SELECT' src/` would. See LOW-W2A-6 below. PASS on substance, FAIL on stylistic guard alignment.
- **`limit` coerced via `int()` AND clamped to `LIMIT_MAX`**: PASS — `_clamp_limit` (L101-107) does `int(limit)` then `min(max(n, 1), LIMIT_MAX)`. Called by `query_active_dispatches` (L302), `query_recent_events` (L328), `query_routing_history` (L360). The clamp lower bound of 1 (not 0) is sensible.
- **`project` validated against `PROJECT_NAME_REGEX` BEFORE persistence**: PASS — `_validate_project` (L94-98) called at every persistence write: `insert_dispatch` (L187), `insert_observer_cycle` (L238), `insert_status_write` (L255), `query_active_dispatches` (L304). Uses `re.match` — *technically* `re.fullmatch` would be more idiomatic for a whitelist, but the regex pattern has `^` AND `$` anchors so `re.match` is anchored to both ends. PASS with stylistic note.
- **`source` field restricted to {"ws","cli","adapter"}**: PASS — `_KNOWN_SOURCES` (L110), `_validate_source` (L114-117), called in `insert_routing_change` (L274).
- **`action` field restricted to {"priority_change","burst_start","lock","release"}**: PASS — `_KNOWN_ACTIONS` (L111), `_validate_action` (L120-123), called in `insert_routing_change` (L275).
- **NO `executescript()` with user input**: PASS — single call at L151 `conn.executescript(_SCHEMA_DDL)` where `_SCHEMA_DDL` is a static module-level constant (L32-81). Comment `# safe – static string` at L151 documents intent.
- **NO views/triggers in v0.1.0**: PASS — DDL contains only CREATE TABLE statements.
- **PRAGMA foreign_keys=ON, journal_mode=WAL on every connection**: PARTIAL — set at `init_db` L148-150, but `init_db` is one-shot per process (sets module-level `_connection`). If a future caller closes and reopens the connection, the PRAGMAs would not re-apply automatically. Acceptable for v0.1.0 since `_connection` is a singleton. PASS for the stated v0.1.0 contract.
- **All 5 tables present**: PASS — `dispatches` (L33), `fallbacks` (L46), `observer_cycles` (L55), `status_writes` (L63), `routing_changes` (L71). All include `IF NOT EXISTS`. Schema columns match v1.2 §4 + MED-9 exactly.
- **UUIDs via `uuid.uuid4().hex` (32 chars, no hyphens)**: PASS — L188 `dispatch_id = uuid.uuid4().hex`.

Cross-cutting: No `os.system`/`subprocess`/`exec`/`eval`. No `os.environ[]` subscript (no `os.environ` use at all). Imports stdlib only (`contextlib`, `re`, `sqlite3`, `uuid`, `pathlib`, `typing`) — matches packet allow-list exactly.

Findings:
- **MED-W2A-3** `db.py:239` — **Unsafe ad-hoc JSON serialization for `flags`.** `insert_observer_cycle` builds the JSON string manually: `flags_str = "[" + ", ".join(f'"{f}"' for f in flags) + "]"`. This is *not* SQL injection (the value goes through `?` binding), but it IS a JSON injection vector — any `flag` value containing a `"`, `\`, control character, or non-ASCII high-bit byte will produce **invalid JSON** that downstream consumers (dashboard, observer retro) cannot parse. The fix is trivially `flags_str = json.dumps(flags)` with `import json` added. This may be a DeepSeek-v4-flash artifact — v4-flash is known to occasionally hand-roll serialization rather than use stdlib helpers. v1.2 doesn't explicitly mandate `json.dumps` here, but it's the only correct option.

- **MED-W2A-4** `db.py:141` — **Third state-dir resolution.** `Path.cwd() / "state" / DB_FILE_NAME`. Same drift as `dpapi.py:157` and divergent from `files.py:48`. See MED-W2A-2 for context. If `harness` is run from a directory other than the repo root, the SQLite history DB ends up in `./state/history.db` (cwd-relative) while pydantic state writes go to `<repo>/state/`. Operator can lose query history simply by `cd`'ing.

- **LOW-W2A-6** `db.py:329` — `sql = f"""..."""` for `query_recent_events`. No interpolation — the f-string is cosmetic. No injection vector, BUT (a) the v1.2 §4.1 CI guard intent is "no f-string SQL at all" to prevent regression, and (b) it's misleading to readers who may add an `{interpolation}` later thinking it's already an f-string template. Replace with plain triple-quoted string: `sql = """..."""`.

- **LOW-W2A-7** `db.py:96` — `re.match(PROJECT_NAME_REGEX, project)` instead of `re.fullmatch`. The pattern has `^...$` so `re.match` works identically here, but `re.fullmatch` is the canonical idiom for whitelist validation and is robust if the regex is ever edited to remove anchors.

- **LOW-W2A-8** `db.py:87, 137` — Module-level mutable singleton `_connection: sqlite3.Connection | None = None` with `global _connection` mutation in `init_db`. Not a security issue but makes testing harder and creates a known footgun: calling `init_db` twice in the same process silently leaks the first connection without close. Not in scope for this audit; flagging for Wave 2B awareness.

Verdict: **PASS** — all HIGH-11 + MED-9 requirements substantively met. The two MED findings are fixable in <10 LOC each.

---

## Cross-file findings

- **CROSS-1 (MED, addressed under MED-W2A-2 and MED-W2A-4)** — Three different `state/` directory resolution strategies across three engine outputs:
  - `dpapi.py:157` → `Path.cwd() / "state"`
  - `db.py:141` → `Path.cwd() / "state" / DB_FILE_NAME`
  - `files.py:48` → `Path(__file__).resolve().parents[3] / "state"`
  Recommend hoisting a single `STATE_DIR` (or `state_dir() -> Path` callable) to `_constants.py` and using it in all three modules. This is exactly the type of duplicate-source-of-truth drift `_constants.py` was created to prevent.

- **CROSS-2 (MED, addressed under MED-W2A-1)** — Two different "project name" regexes (`loader.py:50` is `[a-zA-Z0-9_-]{1,64}` for filesystem-side validation, `_constants.PROJECT_NAME_REGEX` is `[a-z0-9-]{1,32}` for DB-side validation). The asymmetry is defensible (filesystem is more permissive than the DB key column), but it produces silent late failures: a project that loads via `load_project_adapter("My_Project_v2")` will be rejected by `db._validate_project` at first dispatch with `ValueError: Invalid project name`. Either harmonize the regexes or document the constraint chain.

- **CROSS-3 (LOW)** — No file imports `os.environ[]` (subscript). All env access uses `os.environ.get(...)` — see `loader.py:54-56`. Compliant with v1.2 CI guard. PASS across all 5 files.

- **CROSS-4 (LOW)** — No `os.system`, `os.popen`, `subprocess.run(shell=True)`, `subprocess.run` (any form), `exec(`, `eval(`, `yaml.load(`, `yaml.unsafe_load`, `yaml.FullLoader`, `pickle.load*`, or `marshal.load*` anywhere in the 5 audited files. PASS.

- **CROSS-5 (LOW)** — No hardcoded credentials, no suspicious URLs (no external `http://` / `https://` literals at all), no debug endpoints, no `0.0.0.0` bind addresses, no admin-elevation requests, no shell metacharacter passthrough. PASS.

- **CROSS-6 (HIGH, addressed under HIGH-W2A-1)** — `files.py` imports `win32security`, `ntsecuritycon`, `win32api` (pywin32). None are in `pyproject.toml`. This breaks any clean install on Windows the moment a state write happens. The dpapi.py packet explicitly disallows pywin32 ("stdlib only ... NO pywin32 dependency"). While the state-files packet doesn't repeat that prohibition verbatim, its import allow-list omits pywin32 and its file-mode instruction is `os.chmod` — not ACL. Kimi over-implemented without the dependency being declared.

---

## Verdict

**needs-amendment**

Must-fix before Wave 2B:
1. **HIGH-W2A-1** (`files.py`): remove pywin32 ACL branch, use unconditional `os.chmod(path, 0o600)`. Optionally, if Windows ACL hardening is genuinely needed, do it in a separate Wave 2B module with `pywin32-ctypes` added to `pyproject.toml` and proper deny-Everyone semantics.

Should-fix (recommend rolling in with the must-fix):
2. **MED-W2A-3** (`db.py:239`): replace hand-rolled JSON concat with `json.dumps(flags)`.
3. **CROSS-1 / MED-W2A-2 / MED-W2A-4**: introduce single `STATE_DIR` source in `_constants.py`, replace in all three modules.
4. **MED-W2A-1 / CROSS-2**: either harmonize the project-name regexes or add a comment at each call site explaining the chain.
5. **LOW-W2A-4** (`loader.py`): implement actual case-insensitive forbidden-prefix check on Windows.
6. **LOW-W2A-6** (`db.py:329`): strip the cosmetic `f` prefix from the static SQL string.

Counts: **HIGH: 2** (HIGH-W2A-1 + CROSS-6 are the same finding viewed two ways — counting once: 1), **MED: 4** (W2A-1, W2A-2, W2A-3, W2A-4), **LOW: 5** (W2A-1, W2A-2, W2A-3, W2A-5, W2A-6, W2A-7, W2A-8 collapsed where overlapping; final unique count: 5).

Revised counts: **HIGH: 1 / MED: 4 / LOW: 5 / Verdict: needs-amendment**
