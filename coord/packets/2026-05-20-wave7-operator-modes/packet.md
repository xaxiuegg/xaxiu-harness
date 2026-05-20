# Packet: Wave 7 — Operator-modes CLI + adapter YAML

## Mission

Implement the operator-modes config surface per `spec/operator-modes.md`. Surfaces 7 directives as first-class CLI flags, env vars, and adapter YAML keys with proper precedence (CLI > env > YAML > default).

## In-scope deliverables

NEW files:
- `src/harness/operator/__init__.py` — re-exports
- `src/harness/operator/modes.py` — `OperatorMode` StrEnum + `OperatorConfig` Pydantic model
- `src/harness/operator/config.py` — precedence resolver (CLI dict → env → YAML → default)
- `src/harness/operator/flags.py` — Click decorator factory to apply flags to any verb
- `tests/test_operator_modes.py` — precedence + parsing tests

MODIFIED files:
- `src/harness/adapters/schema.py` — add optional `OperatorSection` model to `AdapterConfig` (`operator: OperatorSection | None`)
- `src/harness/cli.py` — apply the flags decorator to the top-level `@cli.group()` so all subcommands inherit
- `src/harness/cli.py` — `dispatch` verb: read `operator.mode`; if `dry_run`, print plan and exit 0
- `src/harness/cli.py` — `init` verb: emit the new `operator` section in generated adapter YAML using defaults

## Schema (the truth — match `spec/operator-modes.md` exactly)

`OperatorMode = StrEnum`:
- `REVIEW_EACH = "review_each"` (default)
- `FULL_DEV_AUTHORITY = "full_dev_authority"`
- `DRY_RUN = "dry_run"`

`OperatorConfig` Pydantic v2 model with fields:
- `mode: OperatorMode = OperatorMode.REVIEW_EACH`
- `escalation_threshold: Literal["L1","L2","L3","L4","L5"] = "L5"`
- `engine_fill: Literal["aggressive","conservative","manual"] = "aggressive"`
- `max_parallel_supervisors: int = Field(default=4, ge=1, le=16)`
- `explore_on_uncertainty: Literal["dispatch_alternatives","inline","ask_operator"] = "dispatch_alternatives"`
- `observer_cadence_minutes: int = Field(default=60, ge=5, le=1440)`
- `profile: Literal["technical","non_technical"] = "technical"`
- `engine_routing: dict[str, str]` (phase → backend; defaults match dev_loop state.json)
- `engine_slots: dict[str, int]` (backend → max_parallel)
- `notifications: dict[str, str]` (method, target)

## Click integration

`apply_operator_flags()` returns a list of click.option decorators. Applied to `cli` group so every subcommand sees `--mode`, `--escalation-threshold`, etc. Stored in click context's `obj`.

```python
@cli.group()
@apply_operator_flags()
@click.pass_context
def cli(ctx, mode, escalation_threshold, ...) -> None:
    ctx.obj = resolve_operator_config(
        cli_overrides={"mode": mode, ...},
        env=os.environ,
        adapter_yaml=load_active_adapter_optional(),
    )
```

Subcommands access via `ctx.obj` (or `click.get_current_context().obj`).

## Tests required

`tests/test_operator_modes.py` should cover:
1. Defaults: omit everything → `OperatorMode.REVIEW_EACH`, escalation L5, etc.
2. YAML-only override: load an adapter with `operator.mode: full_dev_authority` → that wins.
3. Env-only override: set `HARNESS_MODE=dry_run` with no CLI/YAML → that wins.
4. CLI-only override: pass `--mode review_each` with env=full_dev_authority and YAML=dry_run → CLI wins.
5. Validation: invalid mode string raises Pydantic ValidationError.
6. Range: `max_parallel_supervisors=0` and `=17` both rejected.
7. `init` verb emits a new adapter that includes the `operator` section with defaults.

## Acceptance criteria

1. `python -m pytest tests/ -q` shows 89 + new tests, all green.
2. `harness --help` displays the new flags.
3. `harness init -p _test_op_modes -t basic` produces an adapter with the `operator` section.
4. `HARNESS_MODE=dry_run harness dispatch -p X --packet Y.md` exits 0 with "dry-run: would dispatch ..." output, no actual dispatch.
5. Single commit: `feat(operator): operator-modes CLI flags + adapter YAML (Wave 7)`.

## Reference

- `spec/operator-modes.md` — full spec; this packet is the implementation
- `coord/dev_loop/state.json::operator_directives` — current runtime values to use as defaults
- Memory `feedback_operator_inputs_become_harness_config` — origin of this scope
- Memory `feedback_xaxiu_harness_full_dev_authority` — the `full_dev_authority` mode semantics

## Output format

In-place edits to `src/harness/cli.py` + `src/harness/adapters/schema.py`. New files in `src/harness/operator/` and `tests/test_operator_modes.py`. Single commit at the end.
