# Packet: Wave 5/A — Template refresh (adds operator: section)

## Mission

Refresh the existing adapter templates so generated YAML includes the `operator:` section (Wave 7 dependency now satisfied). Each template stays opinionated to its use-case but ships with calibrated `engine_slots` per memory `reference_xaxiu_swarm_concurrency_calibration`.

## In-scope files (modify only)

- `src/harness/adapters/templates/warehouse-style.yaml`
- `src/harness/adapters/templates/generic-coding.yaml`
- `src/harness/adapters/templates/writing-content.yaml`
- `src/harness/adapters/templates/research-comparison.yaml`
- `src/harness/adapters/templates/solo-dev.yaml`
- `src/harness/adapters/templates/basic.yaml`

If `basic.yaml` doesn't exist yet (it's referenced but may not be present), create it as the minimal-safe-defaults template.

## What to add to each template

Append an `operator:` section. Use these per-template values:

| Template | mode | engine_routing.developing | engine_slots.swarm/kimi | engine_slots.swarm/kimi-api | profile |
|---|---|---|---|---|---|
| `warehouse-style` | review_each | swarm/kimi | 6 | 6 | technical |
| `generic-coding` | review_each | swarm/kimi | 6 | 6 | technical |
| `writing-content` | review_each | claude-in-session | 3 | 3 | non_technical |
| `research-comparison` | review_each | swarm/deepseek | 3 | 3 | technical |
| `solo-dev` | **full_dev_authority** | swarm/kimi | 6 | 6 | technical |
| `basic` | review_each | swarm/kimi | 6 | 6 | technical |

Common values across all templates (write into each):
- `escalation_threshold: L5`
- `engine_fill: aggressive`
- `max_parallel_supervisors: 4`
- `explore_on_uncertainty: dispatch_alternatives`
- `observer_cadence_minutes: 60`
- `engine_routing.creativity: claude-in-session`
- `engine_routing.testing: swarm/kimi`
- `engine_routing.integrating: claude-in-session`
- `engine_routing.process_improvement: claude-in-session`
- `engine_slots.swarm/deepseek: 1`
- `notification_method: file`
- `notification_target: coord/dev_loop/escalations.md`

## Validation

Each refreshed template must load cleanly via `harness.adapters.loader.load_template(<name>)`. Add a smoke test in `tests/test_loader.py` (extend existing — don't make a new file) that asserts each template loads AND its `operator` section is present + valid.

## Acceptance criteria

1. All 6 templates have an `operator:` section matching the per-template table.
2. `harness init -p x -t solo-dev` produces an adapter with `mode: full_dev_authority` in the YAML.
3. `python -m pytest tests/ -q` shows ≥185 + new tests, all green.
4. Single commit: `feat(templates): add operator: section to all templates (Wave 5/A)`.

## Reference

- `spec/operator-modes.md` — Wave 7 spec; the `operator:` schema lives there
- `src/harness/operator/modes.py::OperatorConfig` — Pydantic model that validates the YAML
- `spec/wave-5-templates-nl-yaml.md` — Wave 5 spec
- Memory `reference_xaxiu_swarm_concurrency_calibration` — empirically-grounded slot counts

## Output format

In-place YAML edits + minor test extension. Single commit.
