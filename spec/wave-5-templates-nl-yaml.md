# Spec: Wave 5 — templates + NL→YAML translator + visual config builder

## Goal

Give the non-technical operator three escalating ways to produce a valid `harness-adapter.yaml` without hand-writing YAML:

1. **Starter templates** — already exist (Wave 1): `warehouse-style`, `generic-coding`, `writing-content`, `research-comparison`, `solo-dev`, `basic`. Improve them to include `operator:` section (Wave 7 dependency now satisfied).
2. **NL→YAML translator** — operator describes their project in natural language; harness dispatches to swarm/kimi or in-session Claude to produce a draft YAML; operator reviews + saves.
3. **Visual config builder** (post-MVP) — web UI that exposes the schema as a form. Out of scope for v1.

## Scope split

This spec covers **steps 1 + 2 in v1**. Step 3 lives in Wave 5.x or Wave 6.

## Step 1 — Template refresh

Each template in `src/harness/adapters/templates/*.yaml` gains an `operator:` section with safe defaults (`mode: review_each`, `escalation_threshold: L5`, etc.) so generated adapters are immediately usable with the Wave 7 flags.

Refresh per-template emphasis:
- `warehouse-style`: dispatch-heavy; `engine_routing.developing = swarm/kimi`, `engine_slots.swarm/kimi = 3`
- `generic-coding`: balanced; defaults
- `writing-content`: claude-in-session for everything; engine routing weighted toward Claude
- `research-comparison`: deepseek-favored; cross-engine audit on by default
- `solo-dev`: full-dev-authority mode pre-enabled (matches power-user expectation)
- `basic`: safest defaults; mode=review_each, no surprises

## Step 2 — NL→YAML translator

New CLI verb: `harness adapter from-description`

```
harness adapter from-description \
    --project myproj \
    --description "I'm building a Python lib that calls external APIs..." \
    [--engine swarm/kimi | claude-in-session]
```

Flow:
1. Read the `description` (from `--description STR` or `--description-file PATH` or stdin).
2. Dispatch to the chosen engine with a prompt: "Given this project description, produce a valid harness-adapter.yaml. Use the existing schema (extra='forbid'). Choose the closest template + customize from there."
3. Validate the result against `AdapterConfig` schema. If validation fails, retry once with the error feedback ("the previous draft had error X; fix and re-emit").
4. Write to `adapters/<project>/harness-adapter.yaml`. Refuse to overwrite without `--force`.
5. Echo the path and a summary of choices made (e.g. "template basis: generic-coding; mode: review_each").

## Module additions

`src/harness/adapters/from_description.py`:
- `def generate_adapter_from_nl(project: str, description: str, engine: str) -> AdapterConfig`
- Uses `harness.engines.dispatcher.dispatch_packet` internally
- Wraps the prompt template (located at `src/harness/adapters/templates/_nl_to_yaml_prompt.md`)

`src/harness/cli.py`:
- New verb `adapter` (group); `from-description` subcommand
- `adapter list` lists configured projects
- `adapter validate <project>` re-validates an existing YAML

`src/harness/adapters/templates/_nl_to_yaml_prompt.md`:
- The prompt template Kimi (or Claude) sees
- Includes a stripped-down version of the schema + 2-3 example adapters
- Strict output contract: "produce ONLY the YAML, no commentary"

## Acceptance criteria

1. `harness init -p test -t basic` produces YAML with the new `operator:` section.
2. `echo "Python data pipeline" | harness adapter from-description --project test2` produces a valid adapter; pytest-loadable.
3. Validation feedback loop: feeding an intentionally bad description (e.g. random text) does not crash; reports validation error and offers retry.
4. `harness adapter validate test2` exits 0; intentionally corrupting the YAML makes it exit non-zero with `SchemaViolation` message.
5. `python -m pytest tests/test_adapter_from_description.py` covers happy path + retry path + validate verb.
6. Tests pass; coverage doesn't regress on adapters/.

## Engine choice

NL→YAML is a great fit for `swarm/kimi` (agentic, can read templates + write file) OR `claude-in-session` (in-context, no dispatch overhead). Operator picks via `--engine` flag; default `claude-in-session` because the NL input is conversational anyway.

## Non-goals (v1)

- Multi-language description (English only)
- Iterative refinement chat (one-shot generation; `validate` + manual edits handle drift)
- Visual builder UI (Wave 5.x or Wave 6)
- Recommending a template before generation (skip the suggestion step; engine picks during generation)
