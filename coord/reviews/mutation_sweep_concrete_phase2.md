# W6-A3 mutation sweep — top-5 hot modules

_Generated: 2026-05-24T00:46:32.345761+00:00_

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

### `src/harness/engines/concrete.py`  → PASS (avg failed = 3.3)

| Mutation | Applied | Failed | Passed | Duration |
|---|---|---|---|---|
| `bool_return_flip` | (pattern absent) | — | — | — |
| `eq_to_neq` | ✓ | 5 | 1517 | 113.9s |
| `gt_to_ge` | ✓ | 2 | 1520 | 79.2s |
| `is_not_none_to_is_none` | ✓ | 3 | 1519 | 66.6s |
| `plus1_to_minus1` | (pattern absent) | — | — | — |

## Summary

All modules met the ≥3-tests-failed acceptance threshold.
