# Packet: Wave 5/B — NL→YAML translator + `harness adapter` verb group

## Mission

Implement the "describe your project in natural language → get a valid adapter YAML" capability per `spec/wave-5-templates-nl-yaml.md`. Non-technical operators get an adapter without writing any YAML.

## In-scope NEW files

- `src/harness/adapters/from_description.py` — `generate_adapter_from_nl(project, description, engine)`
- `src/harness/adapters/templates/_nl_to_yaml_prompt.md` — the prompt template the engine sees
- `tests/test_adapter_from_description.py` — happy path + retry + validate

## In-scope MODIFY files

- `src/harness/cli.py` — add `adapter` group with subcommands `from-description`, `list`, `validate`

## Specification

### `generate_adapter_from_nl`

```python
def generate_adapter_from_nl(
    project: str,
    description: str,
    engine: str = "claude-in-session",  # or "swarm/kimi"
    max_retries: int = 1,
) -> AdapterConfig:
    """Generate an adapter from a natural-language project description.

    Uses the engine to draft YAML, then validates against AdapterConfig.
    If validation fails, retries up to max_retries with the error as
    feedback. Returns the validated AdapterConfig (caller writes to disk).

    Raises:
        SchemaViolation: if all retries fail validation
        DispatchExhausted: if the engine itself fails (per error taxonomy)
    """
```

The prompt template (`_nl_to_yaml_prompt.md`) includes:
- A stripped-down view of the `AdapterConfig` schema (key fields + types + constraints)
- 2-3 example adapters as worked references
- The user's project description
- Strict output contract: "produce ONLY the YAML between `<<<ADAPTER` and `ADAPTER>>>` markers; no commentary"

For `engine="claude-in-session"`: do NOT dispatch externally; this is the caller's responsibility (they pass in pre-rendered YAML). Skip; v1 supports `swarm/kimi` only. (Update spec accordingly if needed.)

For `engine="swarm/kimi"`: invoke via `harness.engines.dispatcher.dispatch_packet`. Wrap the description in the prompt template (write to a temp packet file), dispatch, read response, extract YAML between markers, validate.

### CLI integration

```python
@cli.group()
def adapter() -> None:
    """Manage harness adapters (alternative to `init`)."""

@adapter.command(name="from-description")
@click.option("--project", "-p", required=True)
@click.option("--description", help="Inline description")
@click.option("--description-file", help="Read description from file")
@click.option("--engine", default="swarm/kimi", type=click.Choice(["swarm/kimi", "swarm/kimi-api"]))
@click.option("--force", is_flag=True)
def adapter_from_description(...): ...

@adapter.command(name="list")
def adapter_list() -> None:
    """List all configured projects with their adapter paths."""

@adapter.command(name="validate")
@click.argument("project")
def adapter_validate(project: str) -> None:
    """Re-validate an existing adapter; exits non-zero on failure."""
```

### Acceptance criteria

1. `echo "Python data pipeline that calls APIs" | harness adapter from-description --project test_nl_001 --description-file -` produces a valid `adapters/test_nl_001/harness-adapter.yaml` AND prints summary of choices made.
2. Intentionally bad description (e.g. random unicode) — function does NOT crash; raises `SchemaViolation` after exhausting retries.
3. `harness adapter validate test_nl_001` exits 0 on the freshly-generated adapter.
4. Corrupting the YAML (delete a required field) → `harness adapter validate test_nl_001` exits non-zero with `SchemaViolation` message.
5. `python -m pytest tests/ -q` shows ≥185 + new tests, all green.
6. Single commit: `feat(adapter): NL→YAML translator + adapter verb group (Wave 5/B)`.

## Engine choice for the dispatch INSIDE this feature

The packet you're reading runs on `swarm/kimi`. The feature being built ALSO uses `swarm/kimi` (or `swarm/kimi-api` if the engine flag is overridden). Don't confuse the two.

## Reference

- `spec/wave-5-templates-nl-yaml.md` — full spec
- `src/harness/adapters/schema.py::AdapterConfig` — validation target
- `src/harness/engines/dispatcher.py::dispatch_packet` — how to call engines

## Output format

3 new files + 1 modified file (cli.py). Single commit.
