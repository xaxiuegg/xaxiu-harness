# Packet: Wave 7/C — Operator-modes schema polish + init verb YAML emission

## Mission

Close out Wave 7 by adding an `OperatorSection` Pydantic model to `src/harness/adapters/schema.py` and wiring `harness init` to emit an `operator:` block when scaffolding a new adapter YAML. Wave 7/A (operator/ module) and 7/B (CLI flag wiring) are done; this packet finishes the schema/init polish that was deferred.

This is a small, low-risk packet — pure file additions + tightly scoped modifications. No dispatcher or state-layer touches.

## In-scope MODIFY files

- `src/harness/adapters/schema.py` — add `OperatorSection` model + thread it into `AdapterConfig` as an optional `operator:` field
- `src/harness/cli.py` — modify the `init` verb so the scaffolded YAML emits a populated `operator:` block (matching the OperatorConfig defaults for the chosen template)
- `tests/test_loader.py` (or `tests/test_schema.py`, whichever has the adapter-loader smoke) — extend with one test asserting `operator:` survives a roundtrip load

## In-scope NEW files

None. Purely additive to existing modules.

## Schema additions (`src/harness/adapters/schema.py`)

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class OperatorSection(BaseModel):
    """Adapter YAML mirror of harness.operator.modes.OperatorConfig.

    Kept structurally distinct from OperatorConfig so the adapter schema
    has one source of truth for YAML validation; the runtime config is
    materialized from this by harness.operator.config.resolve_operator_config.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["review_each", "full_dev_authority", "dry_run"] = "review_each"
    escalation_threshold: Literal["L1", "L2", "L3", "L4", "L5"] = "L5"
    engine_fill: Literal["aggressive", "conservative", "manual"] = "aggressive"
    max_parallel_supervisors: int = Field(default=4, ge=1, le=16)
    explore_on_uncertainty: Literal[
        "dispatch_alternatives", "inline", "ask_operator"
    ] = "dispatch_alternatives"
    observer_cadence_minutes: int = Field(default=60, ge=5, le=1440)
    profile: Literal["technical", "non_technical"] = "technical"
    engine_routing: dict[str, str] = Field(default_factory=dict)
    engine_slots: dict[str, int] = Field(default_factory=dict)
    notification_method: Literal["file", "windows_toast", "email"] = "file"
    notification_target: str = "coord/dev_loop/escalations.md"
```

Add to `AdapterConfig` (the top-level adapter model in the same file):

```python
class AdapterConfig(BaseModel):
    # ... existing fields ...
    operator: OperatorSection | None = None
```

`operator:` is OPTIONAL on existing adapters — backwards-compatible. Existing tests must still pass without the field.

## init verb modification (`src/harness/cli.py`)

The `init` verb scaffolds an adapter YAML. After Wave 7/A landed `harness.operator.modes.OperatorConfig`, the scaffolded YAML should include a populated `operator:` block. Implementation sketch:

```python
from harness.operator.modes import (
    OperatorConfig,
    DEFAULT_ENGINE_ROUTING,
    DEFAULT_ENGINE_SLOTS,
)

def _scaffold_operator_section(template: str) -> dict:
    """Return the operator: section dict for a given template name.

    Templates can override defaults — e.g. solo-dev gets full_dev_authority.
    """
    cfg = OperatorConfig()  # defaults
    if template == "solo-dev":
        cfg.mode = OperatorMode.FULL_DEV_AUTHORITY
    elif template == "writing-content":
        cfg.profile = "non_technical"
        cfg.engine_routing["developing"] = "claude-in-session"
    return cfg.model_dump(mode="json")
```

Then thread `_scaffold_operator_section(template)` into the YAML emitter the `init` verb already uses.

## Tests required

Extend the existing `tests/test_loader.py` (or `tests/test_schema.py`):

1. **Schema validation passes** when `operator:` is present in adapter YAML.
2. **Schema validation passes** when `operator:` is absent (backwards compat).
3. **`mode: full_dev_authority`** survives roundtrip.
4. **Invalid mode** (e.g. `mode: foobar`) raises `ValidationError`.
5. **`harness init -p test -t solo-dev`** smoke (CliRunner): the generated YAML contains `mode: full_dev_authority`.
6. **`harness init -p test -t writing-content`** smoke: generated YAML contains `profile: non_technical` + `developing: claude-in-session`.

## Acceptance criteria

1. `OperatorSection` model present in `src/harness/adapters/schema.py`; wired as optional field on `AdapterConfig`.
2. `harness init -p X -t solo-dev` emits YAML containing a populated `operator:` block with `mode: full_dev_authority`.
3. Existing 263+ tests still pass; 6 new tests added.
4. Single commit: `feat(operator): adapter schema OperatorSection + init verb YAML emission (Wave 7/C)`.

## Reference

- `spec/operator-modes.md` — Wave 7 spec; OperatorSection mirrors the spec
- `src/harness/operator/modes.py::OperatorConfig` — runtime config; this packet's OperatorSection mirrors its fields
- `src/harness/operator/config.py::resolve_operator_config` — precedence resolver; ensure adapter `operator:` participates as the YAML tier
- `src/harness/adapters/schema.py::ObserverConfig` — pattern reference for adding new sections
- Memory `reference_xaxiu_swarm_concurrency_calibration` — slot defaults

## Output format

2 file modifications + 1 test-file extension + 1 commit. No new files. ≤80 LOC of net adds across schema.py + cli.py.
