# W6-A3 mutation sweep — top-5 hot modules

_Generated: 2026-05-23T17:53:20.483468+00:00_

Each mutation is a single-line string-replace applied via `str.replace(..., count=1)`, then `pytest -q` is run against the full suite, then the original file is restored.

**Acceptance threshold** (per W6-A3 spec): ≥3 tests must fail per mutation on average.

## Mutations applied

| Label | Search | Replace |
|---|---|---|
| `bool_return_flip` | `return True` | `return False` |
| `eq_to_neq` | ` == ` | ` != ` |
| `gt_to_ge` | ` > 0` | ` >= 0` |
| `is_not_none_to_is_none` | `is not None` | `is None` |
| `plus1_to_minus1` | ` + 1` | ` - 1` |

## Per-module results

### `src/harness/engines/dispatcher.py`  → PASS (avg failed = 17.3)

| Mutation | Applied | Failed | Passed | Duration |
|---|---|---|---|---|
| `bool_return_flip` | (pattern absent) | — | — | — |
| `eq_to_neq` | ✓ | 2 | 1424 | 110.3s |
| `gt_to_ge` | (pattern absent) | — | — | — |
| `is_not_none_to_is_none` | ✓ | 49 | 1377 | 54.2s |
| `plus1_to_minus1` | ✓ | 1 | 1425 | 75.8s |

### `src/harness/engines/concrete.py`  → FAIL (avg failed = 1.0)

| Mutation | Applied | Failed | Passed | Duration |
|---|---|---|---|---|
| `bool_return_flip` | (pattern absent) | — | — | — |
| `eq_to_neq` | ✓ | 1 | 1425 | 72.5s |
| `gt_to_ge` | (pattern absent) | — | — | — |
| `is_not_none_to_is_none` | ✓ | 1 | 1425 | 71.9s |
| `plus1_to_minus1` | (pattern absent) | — | — | — |

### `src/harness/coord/worker.py`  → FAIL (avg failed = 0.0)

| Mutation | Applied | Failed | Passed | Duration |
|---|---|---|---|---|
| `bool_return_flip` | (pattern absent) | — | — | — |
| `eq_to_neq` | ✓ | 0 | 1426 | 65.6s |
| `gt_to_ge` | ✓ | 0 | 1426 | 76.9s |
| `is_not_none_to_is_none` | (pattern absent) | — | — | — |
| `plus1_to_minus1` | ✓ | 0 | 1426 | 75.4s |

### `src/harness/coord/integrator.py`  → PASS (avg failed = 5.0)

| Mutation | Applied | Failed | Passed | Duration |
|---|---|---|---|---|
| `bool_return_flip` | (pattern absent) | — | — | — |
| `eq_to_neq` | ✓ | 2 | 1424 | 59.5s |
| `gt_to_ge` | ✓ | 1 | 1425 | 73.9s |
| `is_not_none_to_is_none` | ✓ | 12 | 1414 | 64.9s |
| `plus1_to_minus1` | (pattern absent) | — | — | — |

### `src/harness/orchestrator.py`  → FAIL (avg failed = 0.0)

| Mutation | Applied | Failed | Passed | Duration |
|---|---|---|---|---|
| `bool_return_flip` | (pattern absent) | — | — | — |
| `eq_to_neq` | ✓ | 0 | 1426 | 70.0s |
| `gt_to_ge` | ✓ | 0 | 1426 | 69.8s |
| `is_not_none_to_is_none` | (pattern absent) | — | — | — |
| `plus1_to_minus1` | (pattern absent) | — | — | — |

## Summary

Modules NOT meeting the ≥3-tests-failed threshold (follow-up STATUS rows recommended for real-assertion work):

- `src/harness/engines/concrete.py`
- `src/harness/coord/worker.py`
- `src/harness/orchestrator.py`
