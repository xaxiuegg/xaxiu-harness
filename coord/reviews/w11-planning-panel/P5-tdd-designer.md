<!-- persona=P5-tdd-designer status=OK (59041ms) -->

# P5-tdd-designer

## TDD Contract Design — W11 Agent-First Rows

### Top-line Summary

All 10 rows need **isolation-first fixtures** that don't touch real engines or DPAPI. Every contract below is achievable with tmp_path, fake adapters, and monkeypatched secrets — no "run real dispatch" dependencies. The implementer should hit green on all fixtures before touching production code. The audit gate should enforce: each row has ≥3 of 5 tests passing, zero XFAIL markers, and no new skip-reason annotations.

---

### Row-by-Row Test Contracts

#### W11-AGENT-INIT-VERB (`harness agent init --target <path>`)

| Aspect | Specification |
|---|---|
| **Fixture** | `tmp_path` with no `.harness/` dir. Mock adapter registry returning one known project type (e.g., "python"). |
| **Must-have tests** | 1. `init --target tmp_path` creates `.env`, `.harness/state/STATUS.csv`, `.harness/dispatched/`, `CLAUDE.md`, adapter scaffold — assert all paths exist. |
| | 2. Idempotent: running init twice does NOT clobber existing `.env` keys — assert `old_key=old_val` survives. |
| | 3. Missing `--target` defaults to cwd — assert `os.getcwd()` fallback works via monkeypatch. |
| | 4. Invalid target path (nonexistent parent) raises `ClickException` with actionable message — assert exit code ≠ 0. |
| | 5. `CLAUDE.md` contains the agent-context snippet (must have the string `## Harness Agent Context`) — assert substring present. |
| **Integration** | Call `init`, then `harness adapter validate --json` (W11-ADAPTER-VALIDATE-JSON) on the scaffold — expect zero errors. Cross-module: proves scaffold is immediately usable. |
| **Audit gate** | All 5 tests pass. `git diff --stat tmp_path` after init matches a deterministic file list (no extra files). |

---

#### W11-DPAPI-CROSS-PLATFORM

| Aspect | Specification |
|---|---|
| **Fixture** | `.env` file with `OPENAI_KEY=env_val_123` at tmp_path. Monkeypatch `harness.secrets.dpapi.has_secret` to return False (non-Windows). Monkeypatch `resolve_keys` to read from tmp_path/.env. |
| **Must-have tests** | 1. `resolve_keys(["OPENAI_KEY"])` returns `{"OPENAI_KEY": "env_val_123"}` when no DPAPI — assert value matches. |
| | 2. `--encrypt-with-dpapi` flag on Windows path: monkeypatch `has_secret → True`, `decrypt_secret → "dpapi_val"`. Assert DPAPI value wins over .env when flag set. |
| | 3. Missing key in both .env and DPAPI raises `KeyNotFoundError` listing the key name — assert exception message contains key name. |
| | 4. `.env` with malformed line (no `=`) is silently skipped — assert other keys still resolve. |
| | 5. Precedence: .env value chosen when `--encrypt-with-dpapi` NOT set, even if DPAPI has it — assert `"env_val"` returned. |
| **Integration** | `harness agent init` (W11-AGENT-INIT-VERB) writes `.env`, then `resolve_keys` reads it back — round-trip test. |
| **Audit gate** | All 5 tests pass. No test touches the Windows registry hive — all DPAPI calls are mocked. `grep -r "ctypes" tests/` returns zero (no real DPAPI in tests). |

---

#### W11-CLAUDE-MD-TEMPLATE

| Aspect | Specification |
|---|---|
| **Fixture** | Two template files in `harness/templates/`: `python.md`, `generic.md`. Each ≤800 chars. |
| **Must-have tests** | 1. `render_template("python", project_name="myproj")` contains `myproj` and `python`-specific guidance — assert substring. |
| | 2. Unknown project type falls back to `generic.md` — assert no KeyError, generic content returned. |
| | 3. Rendered output is ≤800 chars — `assert len(output) <= 800`. |
| | 4. Template is valid UTF-8 and contains no placeholder tokens (`{{` or `{%`) — assert absence. |
| **Integration** | `harness agent init --type python` (W11-AGENT-INIT-VERB) writes rendered template to `CLAUDE.md` — assert file content matches `render_template("python")`. |
| **Audit gate** | 4 tests pass. All template files pass `wc -c < 800`. |

---

#### W11-PYTHON-SDK-API

| Aspect | Specification |
|---|---|
| **Fixture** | `import harness` is importable. Minimal adapter registered via monkeypatch returning canned response. |
| **Must-have tests** | 1. `from harness import dispatch, retrieve, budget_status` succeeds — assert no `ImportError`. |
| | 2. `dispatch("test prompt")` returns `DispatchResult` with `.summary`, `.metadata`, `.content_ref` attributes — assert all `hasattr`. |
| | 3. `retrieve("fake_id", scope="summary")` calls internal retrieval with correct args — assert via mock spy. |
| | 4. `budget_status()` returns dict with expected keys — assert `isinstance(result, dict)` and keys present. |
| | 5. Type stubs exist: `harness/__init__.pyi` has `dispatch` signature — assert file exists and contains `def dispatch(`. |
| **Integration** | Import the SDK in a subprocess (`python -c "from harness import dispatch"`) — proves no circular imports at module level. |
| **Audit gate** | `mypy harness --strict` passes with zero errors on the public API surface. All 5 tests green. |

---

#### W11-CONTEXT-FRUGAL-RETURN

| Aspect | Specification |
|---|---|
| **Fixture** | Fake engine adapter returning payload with `content` (5000 chars), `metadata` dict, `cost`. |
| **Must-have tests** | 1. `DispatchResult` default attributes: `.summary` is non-empty string ≤200 chars, `.metadata` is dict, `.content_ref` is string (not full content) — assert all. |
| | 2. `.full()` returns the complete content — `assert len(result.full()) == 5000`. Called twice, fetches once (spy on internal loader). |
| | 3. `error_excerpt` present on error results: simulate adapter raising `EngineError` — assert `.error_excerpt` is first 200 chars of traceback. |
| | 4. Tail preservation: last 50 chars of response survive in `.summary` when content ends with key conclusion — assert `content[-50:]` substring in summary or metadata. |
| | 5. No raw content in default serialization: `json.dumps(result)` excludes `.full()` content — assert `"full_content"` not in serialized string. |
| **Integration** | SDK `dispatch()` (W11-PYTHON-SDK-API) returns `DispatchResult` — assert same class, same contract. Cross-row dependency: W11-PYTHON-SDK-API must land first or in same PR. |
| **Audit gate** | All 5 tests green. Memory profile: `tracemalloc` shows `.summary` path allocates <10% of `.full()` path for 50KB payload. |

---

#### W11-DISPATCH-CACHE

| Aspect | Specification |
|---|---|
| **Fixture** | tmp_path with `.harness/dispatched/` dir. Mock engine returning deterministic content for same input. |
| **Must-have tests** | 1. Two identical `dispatch()` calls return same result, engine called once — assert engine mock call count == 1. |
| | 2. Changed prompt content produces cache miss — assert engine called twice for two different prompts. |
| | 3. Changed adapter version (hash) produces cache miss even for same prompt — assert engine called twice. |
| | 4. Cache file is valid JSON on disk in `.harness/dispatched/` — assert `json.load()` succeeds. |
| | 5. `--no-cache` flag bypasses cache — assert engine called even for repeated prompt. |
| **Integration** | `dispatch()` via SDK (W11-PYTHON-SDK-API) + cache hit → `DispatchResult` loads from cache — assert correct type returned. |
| **Audit gate** | All 5 tests green. Cache dir contains ≤2 files per unique (content_hash, adapter_hash) pair. |

---

#### W11-RETRIEVE-API

| Aspect | Specification |
|---|---|
| **Fixture** | Pre-written result file in `.harness/dispatched/{id}.json` with full payload. |
| **Must-have tests** | 1. `retrieve(id, scope="summary")` returns short dict without full content — assert len < 10% of full. |
| | 2. `retrieve(id, scope="full")` returns complete payload — assert all fields present. |
| | 3. `retrieve(id, scope="chunks")` returns list of ≤N chunk dicts — assert `isinstance(result, list)`. |
| | 4. Nonexistent id raises `ResultNotFoundError` — assert exception with id in message. |
| | 5. Corrupted file on disk returns `ResultCorruptedError` — write garbage bytes, assert graceful failure. |
| **Integration** | `dispatch()` returns `content_ref` → `retrieve(content_ref, scope="full")` returns same data — round-trip. Depends on W11-CONTEXT-FRUGAL-RETURN + W11-DISPATCH-CACHE. |
| **Audit gate** | All 5 tests green. Retrieve latency for summary scope < 5ms (assert via `time.monotonic()` delta). |

---

#### W11-AGENT-TELEMETRY

| Aspect | Specification |
|---|---|
| **Fixture** | `budget.record_dispatch` called 3 times with different engines and costs. |
| **Must-have tests** | 1. `budget_status()` returns dict with keys: `offload_ratio`, `remaining_budget`, `dispatches_fired`, `engines_used` — assert all keys present. |
| | 2. `engines_used` is `dict[str, int]` mapping engine name → count — assert types. |
| | 3. `remaining_budget` decreases after a dispatch — assert `before > after`. |
| | 4. `offload_ratio` is float in [0.0, 1.0] — assert bounds. |
| | 5. Empty state (no dispatches) returns zeros, not crash — assert `dispatches_fired == 0`. |
| **Integration** | SDK `budget_status()` (W11-PYTHON-SDK-API) returns same data — same function. |
| **Audit gate** | All 5 tests green. `budget_status()` completes in < 10ms. |

---

#### W11-CROSS-PLATFORM-OBSERVER

| Aspect | Specification |
|---|---|
| **Fixture** | Mock observer cycle function. tmp_path with mock cron file output. |
| **Must-have tests** | 1. `generate_cron_entry()` returns valid crontab string with correct interval — assert regex match `^(\S+\s){5}`. |
| | 2. Cron entry contains absolute path to `harness` CLI — assert no relative path. |
| | 3. On Windows: falls back to Task Scheduler XML generation — assert file written. |
| | 4. `--install` flag writes cron file and prints instructions — capture stdout, assert `crontab` substring. |
| | 5. `--uninstall` flag removes cron entry — assert file cleanup. |
| **Integration** | Observer cycle invoked via cron entry runs `harness observer cycle` — subprocess test with `--dry-run` flag. |
| **Audit gate** | All 5 tests green. Generated cron syntax passes `crontab -l` parse on Linux CI (skip on Windows CI). |

---

#### W11-ADAPTER-VALIDATE-JSON

| Aspect | Specification |
|---|---|
| **Fixture** | Three adapter files: valid, missing-required-field, malformed-syntax. |
| **Must-have tests** | 1. Valid adapter → `validate --json` returns `{"errors": [], "status": "ok"}` — assert `len(errors) == 0`. |
| | 2. Missing field → error object has `field`, `line`, `severity`, `message`, `suggested_fix` keys — assert all keys present. |
| | 3. `severity` is one of `"error"`, `"warning"` — assert value in set. |
| | 4. Malformed Python → `line` points to actual error line — assert `line > 0`. |
| | 5. Exit code 0 for valid, 1 for errors — assert via subprocess return code. |
| **Integration** | `harness agent init` (W11-AGENT-INIT-VERB) scaffolded adapter passes `validate --json` — end-to-end bootstrap validation. |
| **Audit gate** | All 5 tests green. JSON output is valid per `json.loads` — no trailing commas or control chars. |

---

### Two Open Questions

1. **W11-DISPATCH-CACHE and W11-CONTEXT-FRUGAL-RETURN are tightly coupled** — should they land in one PR (single cache key includes content_ref) or does the operator want the cache to store the *full* payload (making .full() a no-op on cache hit)? This changes the cache schema and test #5 on CONTEXT-FRUGAL-RETURN.

2. **W11-CROSS-PLATFORM-OBSERVER cron test** — the test assumes a Linux CI runner for syntax validation. Does the operator have a Windows CI lane, or should the Windows branch be XFAIL-gated with a skip reason?

### Alignment Check

- **Reorder**: W11-PYTHON-SDK-API should land before W11-CONTEXT-FRUGAL-RETURN and W11-RETRIEVE-API — the other three Wave 11-B rows import from it. Currently they're same wave but no explicit dependency chain.
- **Merge**: W11-AGENT-TELEMETRY has only SDK surface; merge its public API test into W11-PYTHON-SDK-API's test file to avoid a stub-only test module.
- **Split**: W11-DPAPI-CROSS-PLATFORM has two distinct behaviors (`.env` reading + DPAPI opt-in). Split the `.env` reader into its own internal module with 3 tests, keeping the DPAPI flag logic separate — the current row conflates platform-detection with config-resolution.
