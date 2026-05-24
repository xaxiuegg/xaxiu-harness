# Mutation canary — src/harness/dashboard/app.py

_Generated: 2026-05-24T08:43:31.226317+00:00_

- Module: `src/harness/dashboard/app.py`
- Mutations applied: 2/3
- Mutations killed: 2/2 (canary PASS)
- Total duration: 360.9s
- Next module in rotation: `src/harness/engines/concrete.py`

## Per-mutation results

| Label | Applied | Killed | Failed Tests | Duration | Notes |
|---|---|---|---|---|---|
| `bool_return_flip` | no | — | — | — | pattern 'return True' not present in module |
| `eq_to_neq` | yes | yes | 1 | 180.0s |  |
| `gt_to_ge` | yes | yes | 1 | 180.0s |  |
