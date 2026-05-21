# Packet: adapters/from_description.py coverage uplift (65% → ≥85%)

## Mission

`src/harness/adapters/from_description.py` (Wave 5/B NL→YAML translator) is at 65% coverage. Uncovered paths: validation-failure retry loop, YAML extraction edge cases (no fences, missing markers), engine error paths. Bring to ≥85% by adding tests that mock `dispatch_packet` and exercise each branch.

Test-only packet. No source code changes.

## In-scope MODIFY files

- `tests/test_adapter_from_description.py` — extend with edge-case tests

## In-scope NEW files

NONE.

## Test additions

For `generate_adapter_from_nl`:

1. Engine returns valid YAML wrapped in `<<<ADAPTER` / `ADAPTER>>>` markers → parsed correctly
2. Engine returns YAML with no markers, just bare YAML → fallback parse succeeds
3. Engine returns YAML with extra commentary before/after → markers extract clean YAML
4. Engine returns invalid YAML on first try, valid on second (retry path)
5. Engine returns invalid YAML on all retries → raises SchemaViolation
6. Engine response that parses as YAML but fails AdapterConfig validation → raises SchemaViolation after retries
7. dispatch_packet returns success=False → raises DispatchExhausted
8. Empty description (whitespace only) → still produces a packet, dispatches normally
9. Description with > 10000 chars → truncated or passed-through (test the documented behavior)
10. force_engine override (e.g. "swarm/kimi-api") → propagates correctly to dispatch_packet call

Target ≥8 new tests. Final coverage on from_description.py ≥85%.

## Acceptance criteria

1. `pytest tests/test_adapter_from_description.py -q` green.
2. `pytest --cov=src/harness/adapters/from_description --cov-report=term tests/test_adapter_from_description.py` ≥85%.
3. `pytest tests/ -q` full suite green.
4. Single commit: `test(adapters): from_description.py coverage uplift (65% → ≥85%)`.

## Reference

- `src/harness/adapters/from_description.py` — module being tested
- `tests/test_adapter_from_description.py` — existing tests (extend)
- `src/harness/engines/dispatcher.py::dispatch_packet` — mock target

## Output format

1 test-file extension + 1 commit. No source code changes.
