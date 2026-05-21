# Packet: engines/dispatcher.py coverage uplift (75% → ≥90%)

## Mission

`src/harness/engines/dispatcher.py` is the auto-fallback orchestrator — the most critical correctness path in the harness. Currently at 75% coverage; the 25% gap is mostly the fallback-chain branches + jsonl-logging exception swallowing. Bring to ≥90% by adding focused tests that mock the engine layer and exercise each early-return path + each fallback branch.

Test-only packet. No source code changes.

## In-scope MODIFY files

- `tests/test_engines_concrete_boundary.py` OR `tests/test_dispatcher.py` if it exists; otherwise create `tests/test_dispatcher_paths.py`

## In-scope NEW files

`tests/test_dispatcher_paths.py` if no dispatcher-focused test file exists yet.

## Test additions

Verify each early-return path in `dispatch_packet`:

1. invalid project name → `error="invalid_project_name"`, dispatch_id == ""
2. unsupported force_engine → `error="unsupported_force_engine"`
3. adapter load failure → `error="adapter_load_failed: ..."`
4. packet path missing → `error="packet_read_failed: ..."`
5. engine_health corrupt → `error="engine_health_corrupt: ..."`
6. `_pick_initial_engine` raising → `error="engine_selection_failed: ..."`
7. state_db.insert_dispatch failure → `error="db_insert_failed: ..."`
8. state_files.append_active_dispatch failure → silently swallowed, dispatch continues (best-effort path)
9. successful single dispatch (no fallback) → success=True, fallback_chain == [primary]
10. primary engine fails + alternate succeeds → success=True, fallback_chain has 2 entries, fallback row inserted
11. all engines fail → success=False, error="all_fallbacks_exhausted: ..."
12. locked engine + locked engine fails → "locked_engine_failed" error path
13. wave_id parameter present → status_hooks.on_dispatch_start + on_dispatch_complete invoked (mocked)
14. wave_id present but hooks raise → swallowed, dispatch result unchanged

Target ≥10 new tests. Final dispatcher.py coverage ≥90%.

## Acceptance criteria

1. `pytest tests/ -q` green.
2. `pytest --cov=src/harness/engines/dispatcher --cov-report=term` reports ≥90%.
3. Single commit: `test(dispatcher): early-return + fallback-chain coverage (75% → ≥90%)`.

## Reference

- `src/harness/engines/dispatcher.py` — module being tested
- Existing boundary tests in `tests/test_engines_concrete_boundary.py` for mock patterns

## Output format

1 test file (new OR extension) + 1 commit. No source code changes.
