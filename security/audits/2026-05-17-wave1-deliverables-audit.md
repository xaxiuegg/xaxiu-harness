# Wave 1 Deliverables Security Audit
**Auditor:** general-purpose agent
**Date:** 2026-05-17
**Files audited:** schema.py (206 LOC), cli.py (197 LOC), engines/base.py (159 LOC)

## Summary
- HIGH severity findings: 0
- MED severity findings: 2
- LOW severity findings: 5
- Files clean: `engines/base.py` (zero findings; all required patterns implemented exactly as specified)

## Per-file findings

### schema.py (DeepSeek v4-flash)

Required pattern checks:
- **`yaml.safe_load` exclusively, never `yaml.load`**: PASS
  - Line 196: `data = yaml.safe_load(f)` with explicit comment `# ONLY safe_load – never load()` on line 195.
  - No occurrence of bare `yaml.load(` anywhere in the file.
- **No `eval`/`exec`**: PASS
  - Grep on file shows zero `eval(` or `exec(` calls.
- **Path traversal prevention in `project_root`**: PASS
  - Lines 156-157: `if ".." in v.split("/") or ".." in v.split("\\"): raise ValueError(...)`. Segment-wise match (not substring) — correctly avoids false positives on legitimate paths like `/tmp/foo..bar/` while catching `..` as a directory component.
  - Line 150: `if not path.is_absolute()` enforces absolute paths (with the documented `{{PROJECT_ROOT}}` placeholder escape).
- **Reject shell metacharacters in `command`**: PASS
  - Line 113: `forbidden_chars = set(";|&` + "`" + `$()")` — contains all 6 required characters (`;`, `|`, `&`, backtick, `$`, `(`, `)`).
  - Line 114: `if any(c in v for c in forbidden_chars): raise ValueError(...)`.
- **String fields capped at reasonable max_length**: PASS (mostly)
  - `name` max 64 (line 124), `project_root` 4096 (line 125), `command` 4096 (line 93), `cron` 256 (line 92), `if_` 256 (line 35), `reason` 1024 (line 37), `model` 128 (line 28).
- **Reject `flag_patterns` regex compiling to catastrophic backtracking — basic length check (<512)**: PASS (length), DEFERRED (nested-quantifier detection)
  - Lines 78-81: length check raises for `len(pattern) >= 512`. Required by spec.
  - Lines 82-85: nested-quantifier check (`\(.*\)\+` etc.) found-but-not-acted-on (`pass` with comment "Wave 2"). Spec only required basic length check, so this is acceptable as a documented deferral, but see finding S-LOW-3.
- **`name`: alphanumeric + underscore + hyphen only, max length 64**: PASS
  - Line 131: `_name_pattern = re.compile(r"^[a-zA-Z0-9_-]+$")`.
  - Lines 135-141: pattern + length check.
- **`cron`: 5-field cron expression check**: PASS
  - Line 96: `_cron_regex = re.compile(r"^(\S+\s+){4}\S+$")` enforces exactly 5 whitespace-separated fields.
- **`daily_retro_time`: HH:MM 24h format**: PASS
  - Line 70: `re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v)` — correctly bounds hours 00-23 and minutes 00-59.
- **`command`: must start with `"harness "`**: PASS
  - Line 110: `if not v.startswith("harness "): raise ValueError(...)`.
- **`routing_rules[].if_`: max length 256**: PASS
  - Line 35: `if_: str = Field(alias="if", max_length=256)`.

Findings:
- **S-MED-1 (severity: MED)** — Nested models do not set `extra: "forbid"`. Only `AdapterConfig` (line 174-176) rejects unknown fields. `RoutingAction`, `RoutingRule`, `StatusTrackingConfig`, `ObserverConfig`, `RoutingRule`, and `ScheduledTask` will silently accept and discard unknown nested fields. A malicious or accidental adapter YAML could smuggle fields that look meaningful but are ignored, masking misconfiguration. Recommend adding `model_config = {"extra": "forbid"}` to all nested models — or set `extra="forbid"` at a shared base class level.
- **S-LOW-1 (severity: LOW)** — Contradictory length cap on `RoutingRule.if_`. Line 35 caps `if_` at `max_length=256` via Pydantic Field, but the validator on line 44 only raises for `len(v) >= 512`. The Pydantic cap wins (effective limit is 256), so the validator is dead code. Either align them to 256 or remove the validator. Not exploitable, but confusing and likely indicates the spec was implemented twice with inconsistent numbers.
- **S-LOW-2 (severity: LOW)** — `StatusTrackingConfig.config` (line 53) and `RoutingAction.extra_args` (line 29) accept `dict[str, Any]` with no recursion depth or total-size limit. A pathological YAML with deeply nested or extremely large `config` could exhaust memory during validation. PyYAML safe_load has some default limits, but Pydantic will accept whatever it gets. Document expected shape and consider depth/size caps in Wave 2.
- **S-LOW-3 (severity: LOW)** — Catastrophic-backtracking detection on `flag_patterns` (lines 83-85) is a documented no-op (`pass`). Comment says "deferred to Wave 2". This matches the spec ("basic check: pattern length <512" — implemented separately on lines 78-81), so this is informational only. Track in Wave 2 backlog.
- **S-LOW-4 (severity: LOW)** — `load_adapter(path)` (line 179) accepts arbitrary file paths with no validation that `path` is inside an expected directory. A caller passing a user-controlled path could read any file readable by the process (e.g., `~/.aws/credentials`) and surface it as a YAML parse error. Worst case is information disclosure via error messages — line 203 includes `{exc}` in the wrapped `ValueError`, which could leak file content fragments if Pydantic includes them in validation errors. Recommend either (a) restrict `path` to a project-config directory, or (b) sanitize the error message before raising. Caller-side hardening also acceptable.

### cli.py (Kimi)

Required pattern checks:
- **`env` verb uses the exact required pattern**: PASS
  - Lines 110-116, verbatim:
    ```python
    keys = ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"]
    for key_name in keys:
        val = os.environ.get(key_name)
        if val:
            click.echo(f"{key_name}: SET")
        else:
            click.echo(f"{key_name}: MISSING")
    ```
  - This is byte-identical (modulo loop wrapper) to the required pattern. No `click.echo(f"{key_name}: {val}")` anywhere — verified.
- **All stubs use `click.echo` not `print`**: PASS
  - Zero occurrences of `print(` in the file; every output uses `click.echo(...)`.
- **Each stub returns appropriate exit code**: PARTIAL PASS — see finding C-LOW-1
  - Every command ends with `sys.exit(0)` — the function does exit, but `0` denotes success even though the body says "not implemented yet". This is contestable; spec says "appropriate" which could be read either way.

Findings:
- **C-MED-1 (severity: MED)** — `env` verb has a dead `--show-set` flag plus an unconditional `"not implemented yet"` epilogue (lines 117-119). The `--show-set` option (line 107) is documented as "Show which API keys are set" — but the loop on lines 111-116 *already* shows exactly that, unconditionally. When `--show-set` is passed, the command additionally prints `"env: show_set=True"` (line 118), which leaks no secret but is confusing. More importantly, the final `click.echo("not implemented yet")` (line 119) contradicts the fact that the SET/MISSING reporting *is* implemented and working. Recommend removing both the dead flag and the trailing "not implemented yet" line so the verb's behavior matches its documented purpose. Severity is MED because users may believe `env` is non-functional and proceed without checking their keys.
- **C-LOW-1 (severity: LOW)** — All stubs exit with `sys.exit(0)` (success). For unimplemented commands, exit code `2` (per typical CLI convention for "command misuse") or a custom `127` (command not found) would be more accurate. Calling `dispatch` in a script today will silently "succeed" with no action taken. Low because Wave 2 will replace these bodies, but worth fixing now to avoid downstream scripts wrongly believing dispatch occurred.
- **C-LOW-2 (severity: LOW)** — The `dispatch` verb (line 38) echoes `packet=...` to stdout including the path provided by the user. Not exploitable (it's the user's own input) but consider redacting in Wave 2 if `--packet` ever accepts URLs that could contain tokens (e.g., `https://github.com/...?token=...`).

Cross-cutting positives:
- No `os.system`, `subprocess`, `os.popen`, `eval`, `exec` anywhere in the file.
- No hardcoded credentials.
- `dashboard_serve` defaults to port `7878` with no `--bind` option — it does NOT default to `0.0.0.0` (no bind host shown in stub) — safe default deferred to Wave 2 implementation.
- Imports limited to `os`, `sys`, `typing.Optional`, and `click` (declared dep).

### engines/base.py (Kimi)

Required pattern checks:
- **`__init__` reads API key via `os.environ.get(name)` (never `os.environ[name]`)**: PASS
  - DeepSeekEngine line 79: `api_key = os.environ.get("DEEPSEEK_API_KEY")`.
  - KimiEngine line 111: `api_key = os.environ.get("KIMI_API_KEY")`.
  - AnthropicEngine line 141: `api_key = os.environ.get("ANTHROPIC_API_KEY")`.
  - Zero occurrences of `os.environ[` subscript access — verified by inspection.
- **`__repr__` shows `"api_key=SET"` or `"api_key=MISSING"`, never the actual value**: PASS
  - DeepSeekEngine line 97: `return f"DeepSeekEngine(api_key={'SET' if self._api_key else 'MISSING'})"`.
  - KimiEngine line 129: `return f"KimiEngine(api_key={'SET' if self._api_key else 'MISSING'})"`.
  - AnthropicEngine line 159: `return f"AnthropicEngine(api_key={'SET' if self._api_key else 'MISSING'})"`.
  - All three are identical pattern; the conditional only ever interpolates the literal strings `'SET'` or `'MISSING'` — the actual key value is never referenced in the f-string. Additional benefit: empty-string keys (`""`) are falsy and correctly report `MISSING`, avoiding leak of placeholder values.
- **No `__str__` override that exposes the key**: PASS
  - No `__str__` method defined anywhere — Python defaults `__str__` to `__repr__`, which is the safe sanitized form.
- **`dispatch` stubs do not include api_key in output**: PASS
  - All three engines' `dispatch` (lines 86-94, 118-126, 148-156) return an `EngineResponse` with `text=""`, `error="dispatch not implemented in Wave 1"`. No reference to `self._api_key` or any key material in the response.
- **`SUPPORTED_BACKENDS = ["deepseek", "kimi", "anthropic"]`**: PASS
  - Line 19, exact match.

Findings:
- (none)

Positive observations:
- `EngineResponse` is `@dataclass(frozen=True)` (line 22) — immutable, defends against accidental field mutation that could allow another code path to inject a key into the response after construction.
- All three concrete engines store the key in a single-underscore-prefixed attribute (`self._api_key`), which is a documentation convention for "private" but does not enforce access control. Acceptable for Wave 1; Wave 2 might further wrap behind a property that re-sanitizes on every access.
- Wave-2 plans documented in docstrings (lines 68-75, 102-107, 134-137) — informative comments, no executable code being smuggled in.

## Cross-file findings

- **X-LOW-1 (severity: LOW)** — `cli.py` has no integration with `engines/base.py` yet (the `env` verb hardcodes the same three key names independently). This is consistent with Wave 1 scaffolding but means the `SUPPORTED_BACKENDS` constant is currently the only source of truth and the CLI duplicates the key-name list. Worth refactoring in Wave 2 to derive from a single source.
- **No security issues across the file boundary.** No file imports another in a way that bypasses validation. `schema.py` does not import from `engines/base.py` or `cli.py` and vice versa. No circular imports, no shared mutable state.
- **All imports are stdlib or declared dependencies.** Verified against `pyproject.toml`:
  - `schema.py`: `re`, `pathlib.Path`, `typing` (stdlib) + `yaml` (pyyaml) + `pydantic` — all declared.
  - `cli.py`: `os`, `sys`, `typing` (stdlib) + `click` — declared.
  - `engines/base.py`: `os`, `abc`, `dataclasses`, `typing` (stdlib) — no external deps.
- **No suspicious external network calls in module-level code.** Engine stubs do not import `httpx` or `urllib`; they cannot make network calls at all in Wave 1.
- **No backdoor patterns.** No magic env var that bypasses validation, no debug-mode toggle, no hidden imports, no `if os.environ.get("DEBUG_BYPASS"):` style checks.
- **No `__import__`, `compile`, `getattr` with user-controlled name, or other reflection-based escape hatches.**

## Verdict
- **safe-to-proceed** (with recommended pre-Wave-2 amendments)

The three files are functionally and securely scaffolded as specified. All critical security requirements from packets B, C, and D are implemented correctly:
- YAML loading uses `safe_load` only.
- API keys are never written to logs, repr, or response bodies.
- Path traversal and shell metacharacter injection are blocked at the schema layer.
- The CLI `env` verb uses the exact safe pattern that the operator was burned by previously (`feedback_no_env_value_leak_in_shell_checks.md` informed this requirement, per the project's MEMORY.md — this audit confirms compliance).

The two MED findings (S-MED-1 nested-model `extra:forbid` gap, C-MED-1 dead `env --show-set` flag plus misleading "not implemented yet" line) should be fixed before Wave 2 begins building on these foundations, but neither is exploitable today. The five LOW findings are quality/correctness issues worth tracking in the Wave 2 backlog.

**Final tallies: HIGH=0 / MED=2 / LOW=5**

**Verdict: safe-to-proceed**
