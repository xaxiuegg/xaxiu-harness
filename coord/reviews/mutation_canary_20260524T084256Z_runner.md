# Mutation canary — src/harness/loops/runner.py

_Generated: 2026-05-24T08:42:33.293969+00:00_

- Module: `src/harness/loops/runner.py`
- Mutations applied: 1/3
- Mutations killed: 1/1 (canary PASS)
- Total duration: 22.8s
- Next module in rotation: `src/harness/dashboard/app.py`

## Per-mutation results

| Label | Applied | Killed | Failed Tests | Duration | Notes |
|---|---|---|---|---|---|
| `bool_return_flip` | no | — | — | — | pattern 'return True' not present in module |
| `eq_to_neq` | yes | yes | 1 | 22.8s |  |
| `gt_to_ge` | no | — | — | — | pattern ' > 0' not present in module |
