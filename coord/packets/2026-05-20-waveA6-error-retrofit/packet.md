# Packet: Wave A.6 — Retrofit raises to HarnessError subclasses

## Mission

Replace bare `raise ValueError(...)`, `raise RuntimeError(...)`, and other generic exception raises across `src/harness/` with the appropriate `HarnessError` subclass from `src/harness/errors.py` (just landed in Wave A.5). Preserves stable error tagging and prepares the codebase for Wave A.7 (jsonl log gets `error_level` + `error_code` fields).

## Scope

In-scope files:
- `src/harness/engines/dispatcher.py`
- `src/harness/engines/concrete.py`
- `src/harness/engines/guards.py`
- `src/harness/engines/base.py`
- `src/harness/secrets/dpapi.py`
- `src/harness/state/files.py`
- `src/harness/state/db.py`
- `src/harness/state/jsonl_log.py`
- `src/harness/adapters/loader.py`
- `src/harness/adapters/schema.py`

Out-of-scope:
- `src/harness/cli.py` (CLI input validation `ValueError`s remain — Click conventions)
- `src/harness/errors.py` itself (the source)
- `tests/` (only update assertions that check specific exception classes; do not refactor test logic)

## Mapping table

Read `spec/errors.md` for the full taxonomy. The replacement guide:

| Existing raise context | New subclass | Notes |
|---|---|---|
| All engines failed; dispatcher gave up | `DispatchExhausted` | L3 |
| HTTP timeout to engine | `EngineTimeout` | L3 |
| Guard detected refusal pattern | `EngineRefusal` | L3 |
| Guard detected DSML tool-call attempt | `PacketTrap` | L4 |
| JSONL closed-schema validation failed | `SchemaViolation` | L4 |
| YAML parse / Pydantic validation failed for adapter | `ConfigCorruption` | L5 |
| DPAPI encrypt/decrypt failed | `DpapiUnreadable` | L5 |
| Adapter file or required field missing | `ConfigCorruption` | L5 |
| Other / unclear — leave as ValueError or RuntimeError | (no change) | Document in comment if non-obvious |

## Required behavior

1. Each retrofitted raise carries:
   - A descriptive `message` (don't lose context from original raise)
   - Optional `context` dict for relevant key-value details (e.g. `{"file": "state.json"}`, `{"engine": "kimi"}`)
2. Imports updated: each modified file gains `from harness.errors import <subclass>` at the top.
3. Tests that assert `ValueError`/`RuntimeError` get updated to assert the new subclass (but ALSO `HarnessError` should still pass since subclasses inherit).
4. `python -m pytest tests/ -q` must remain green (89/89).
5. Run `python -m pytest tests/ --cov=src/harness --cov-report=term-missing | tail -25` and report coverage delta.

## Implementation guidance

Single-domain refactor; Kimi handles fine. Suggested approach:
- For each file, `grep -n "raise ValueError\|raise RuntimeError" <file>` to find candidates
- Read 5 lines of context around each raise to determine appropriate subclass
- Edit in place; preserve original message text where useful
- Keep changes minimal: don't refactor the surrounding logic, only the raise

## Acceptance criteria

1. All in-scope files now raise `HarnessError` subclasses where the mapping table applies.
2. No `raise ValueError(` or `raise RuntimeError(` remains in the in-scope set unless documented (a one-line `# kept as ValueError because <reason>` comment is acceptable).
3. `python -m pytest tests/ -q` shows 89 passed (or more, if you add tests for new error paths).
4. Test files that assert exception types are updated to the new subclasses.
5. Single commit message: `feat(errors): retrofit raises to HarnessError subclasses (Wave A.6)`.

## Reference

- `src/harness/errors.py` — the subclasses available
- `spec/errors.md` — full taxonomy and exit codes
- Memory `reference_xaxiu_harness_error_taxonomy` (in operator's Claude memory) — operator-confirmed scheme

## Output format

In-place edits to the in-scope files + `tests/test_*.py` where exception-type assertions exist. Single commit at the end.
