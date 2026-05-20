# Spec: Operator modes (Wave 7)

## Goal

Surface every operator-given directive from xaxiu-harness sessions as a first-class CLI flag / YAML config key, analogous to Claude Code's `--bare`, `--effort`, `--dangerously-skip-permissions`. The operator should be able to configure the harness once (per project, via adapter YAML) and have the same semantics persist across sessions, restarts, and machines — rather than re-asserting directives every session.

## Background

The xaxiu-harness dev loop session 2026-05-20 surfaced ~10 distinct operator directives that became load-bearing for autonomous behavior (full-dev-authority, L5 escalation, parallel supervisors, engine slot-fill, cross-engine audit, non-technical profile, etc.). Today these live in operator's Claude memory and the dev loop's manager.md prompt. Wave 7 promotes them to harness-native config.

## CLI flag surface (additions to `harness` top-level)

```
--mode {review_each | full_dev_authority | dry_run}
                              # default: review_each
                              # full_dev_authority enables auto-commit/push/dispatch
                              # dry_run surfaces all proposed actions for operator review
--escalation-threshold L1|L2|L3|L4|L5
                              # default: L5
                              # only escalations at/above this level surface to operator
--engine-fill {aggressive | conservative | manual}
                              # default: aggressive
                              # aggressive = keep cheap-engine slots filled with queued work
--max-parallel-supervisors N  # default: 4
--explore-on-uncertainty {dispatch_alternatives | inline | ask_operator}
                              # default: dispatch_alternatives
                              # when ambiguous, dispatch N=2 packets with alternative framings
--observer-cadence-minutes N  # default: 60
--profile {technical | non_technical}
                              # default: technical
                              # non_technical = no-code-only outputs, simpler error messages
```

Each flag has a matching env var (`HARNESS_MODE`, `HARNESS_ESCALATION_THRESHOLD`, etc.) and a matching adapter YAML key (`adapter.operator.mode`, etc.). Precedence: CLI flag > env var > adapter YAML > default.

## Adapter YAML section

```yaml
operator:
  mode: full_dev_authority           # review_each | full_dev_authority | dry_run
  escalation_threshold: L5           # L1..L5
  engine_fill: aggressive            # aggressive | conservative | manual
  max_parallel_supervisors: 4
  explore_on_uncertainty: dispatch_alternatives
  observer_cadence_minutes: 60
  profile: technical                 # technical | non_technical
  engine_routing:
    creativity: claude-in-session
    developing: swarm/kimi
    testing: swarm/kimi
    integrating: claude-in-session
  engine_slots:
    swarm/kimi: 3
    swarm/kimi-api: 2
    swarm/deepseek: 1
  notifications:
    method: file                     # file | windows_toast | email
    target: coord/dev_loop/escalations.md
```

## Module layout (`src/harness/operator/`)

- `__init__.py`
- `modes.py` — `OperatorMode(StrEnum)` + behavioral helpers (commit_requires_approval, dispatch_requires_approval, etc.)
- `config.py` — Pydantic model for the `operator` section + precedence resolver
- `flags.py` — Click integration: decorator that applies the flags to any verb

## CLI integration (existing verbs gain awareness)

- `harness dispatch` reads operator.mode; if `dry_run`, prints what would be dispatched and exits 0.
- `harness loop start <name> --mode full_dev_authority` is the supported invocation.
- Manager / supervisors read the operator config from `state.json` (which itself reads from adapter on init) — single source of truth at runtime.

## Acceptance criteria for Wave 7

1. `harness --help` lists the new flags.
2. `harness init -p test -t basic` produces an adapter YAML with the new `operator` section using defaults.
3. `harness loop start dev_loop --mode full_dev_authority` overrides the YAML and persists for that loop session.
4. `harness dispatch ... --mode dry_run` does NOT dispatch; prints what would happen.
5. Existing tests pass; new tests cover precedence (CLI > env > YAML > default).
6. `spec/operator-modes.md` referenced from `CLAUDE.md` and the dispatch-rules.

## Non-goals (Wave 7)

- The Wave 6 productization (full loop-as-feature with `harness loop` CRUD verbs) — that's separate. Wave 7 is just the OPERATOR config surface.
- Migration of existing dev_loop state to the new schema — keep both running side-by-side until Wave 6.
- Visual config builder UI — that's a Wave 5/6 item.
