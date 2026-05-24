# Mutation canary — src/harness/proxy/circuit.py

_Generated: 2026-05-24T08:37:52.490052+00:00_

- Module: `src/harness/proxy/circuit.py`
- Mutations applied: 2/3
- Mutations killed: 2/2 (canary PASS)
- Total duration: 184.0s
- Next module in rotation: `src/harness/observer/cycle.py`

## Per-mutation results

| Label | Applied | Killed | Failed Tests | Duration | Notes |
|---|---|---|---|---|---|
| `bool_return_flip` | yes | yes | 1 | 91.4s |  |
| `eq_to_neq` | yes | yes | 1 | 92.6s |  |
| `gt_to_ge` | no | — | — | — | pattern ' > 0' not present in module |
