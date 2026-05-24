# W6-A3 mutation sweep — top-5 hot modules

_Generated: 2026-05-24T00:12:17.246539+00:00_

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

### `src/harness/coord/worker.py`  → PASS (avg failed = 4.0)

| Mutation | Applied | Failed | Passed | Duration |
|---|---|---|---|---|
| `bool_return_flip` | (pattern absent) | — | — | — |
| `eq_to_neq` | ✓ | 6 | 1482 | 120.1s |
| `gt_to_ge` | ✓ | 0 | 1488 | 80.2s |
| `is_not_none_to_is_none` | (pattern absent) | — | — | — |
| `plus1_to_minus1` | ✓ | 6 | 1482 | 76.8s |

## Summary

All modules met the ≥3-tests-failed acceptance threshold.
