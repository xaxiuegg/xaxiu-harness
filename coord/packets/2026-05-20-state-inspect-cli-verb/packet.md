# Packet: `harness state inspect` CLI verb (pretty-print state.json)

## Mission

Surface the dev-loop's `coord/dev_loop/state.json` to a non-technical operator without requiring Python familiarity. Adds a `state` verb group with an `inspect` subcommand that pretty-prints loop status, phase health, active dispatches, wave plan summary, and active escalations.

Roster row aligned with #17 / non-technical-operator-readable surfaces (see `user_non_technical_role` memory). Not the dashboard (Wave 3) — this is the CLI fallback for when the dashboard isn't running or the operator wants a one-shot read.

## In-scope NEW files

- `src/harness/state/inspect.py` — rendering helpers (`render_state_json(path) -> str`, `summarize_wave_plan(plan) -> str`, etc.)
- `tests/test_state_inspect.py` — CLI smoke + rendering correctness + edge cases (empty state, missing file)

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group(name="state") def state()` + `@state.command(name="inspect") def state_inspect()`. Keep cli.py footprint minimal: ≤25 LOC, delegate rendering to `harness.state.inspect.render_state_json`.

## Module API

```python
# src/harness/state/inspect.py
from pathlib import Path
import json

def render_state_json(path: Path = Path("coord/dev_loop/state.json"),
                     fmt: str = "pretty") -> str:
    """Render state.json in operator-readable form.

    fmt:
      - "pretty": multi-section ANSI-colored human summary (terminal-aware)
      - "json": pass-through raw json (machine-readable)
      - "compact": single-line key=val for piping
    """

def summarize_wave_plan(wave_plan: list[dict]) -> str:
    """Single-line summary, e.g. '8 done / 1 in_progress / 4 planned'."""

def summarize_active_dispatches(dispatches: list[dict]) -> str:
    """Multi-line render of in-flight dispatches with elapsed time."""

def summarize_phase_statuses(phase_status: dict[str, str]) -> str:
    """Single-line render, e.g. 'all 5 armed' or '4 armed, 1 paused (testing)'."""
```

Output sketch for `pretty` mode:

```
Loop: armed | tick #11 | last pulsed 2026-05-21T00:02:35Z

Phases: all 5 armed
  creativity: armed (next due 17:30 UTC)
  developing: armed (in flight: 1 dispatch)
  testing: armed
  integrating: armed
  process_improvement: armed (next due 15:30 UTC)

Active dispatches (1):
  dispatch-2026-05-21T00-02-status-tracker  swarm/kimi   wave-5.5   elapsed 02:14

Wave plan: 8 done / 1 in_progress / 4 planned
  Done: wave-A, wave-A.5, wave-A.6, wave-B, wave-B2, wave-4, wave-7, wave-A.1
  In progress: wave-5.5 (status tracker primitive)
  Planned: wave-5, wave-5.6, wave-3, wave-6

Escalations: none active
Engine slots: kimi 1/6, kimi-api 0/6, deepseek 0/1
```

ANSI color cues: armed=green, paused=yellow, escalated=red, planned=dim, done=dim+strikethrough optional. Color disabled with `--no-color` or when stdout is not a TTY (use `click.echo(..., color=...)`).

## CLI verb

```python
# in src/harness/cli.py
@cli.group(name="state")
def state() -> None:
    """Inspect / manipulate the dev-loop runtime state."""

@state.command(name="inspect")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json", "compact"]), default="pretty")
@click.option("--no-color", is_flag=True)
@click.option("--path", type=click.Path(path_type=Path), default=Path("coord/dev_loop/state.json"))
def state_inspect(fmt: str, no_color: bool, path: Path) -> None:
    """Pretty-print coord/dev_loop/state.json for the operator."""
    from harness.state.inspect import render_state_json
    click.echo(render_state_json(path=path, fmt=fmt))
```

## Tests required

1. `render_state_json(missing_path)` raises a `HarnessError` (L3.config) — never silent.
2. `render_state_json(corrupt_json)` raises a `ConfigCorruption` (L5).
3. `render_state_json(valid_path, fmt="json")` returns parseable JSON (roundtrip).
4. `render_state_json(valid_path, fmt="pretty")` contains the section headers ("Loop:", "Phases:", "Active dispatches", "Wave plan:", "Escalations:", "Engine slots:") in order.
5. `summarize_wave_plan` with mixed statuses returns correct counts.
6. `summarize_active_dispatches` with empty list returns "(none)".
7. `harness state inspect` CLI smoke (CliRunner): exit 0, output matches the pretty-mode regex.
8. `harness state inspect --format json` returns the file contents as JSON (roundtrip-equal to `json.load`).
9. `harness state inspect --no-color` strips ANSI codes.

## Acceptance criteria

1. `harness state inspect` against the current `coord/dev_loop/state.json` renders the multi-section summary in under 1 second.
2. `harness state inspect --format json` outputs the raw state for piping (`| jq`).
3. `python -m pytest tests/ -q` shows ≥263 + 9 new tests, all green.
4. Single commit: `feat(state): inspect verb for operator-readable state summary (STATE-INSPECT)`.

## Reference

- `coord/dev_loop/state.json` — source of truth being rendered
- `src/harness/state/files.py` — sibling state-layer module
- `spec/session-derived-feature-roster.md` row #17 — heartbeat is the cousin
- Memory `user_non_technical_role` — operator profile; load-bearing for this output style

## Output format

1 new module + 1 new test file + 1 cli.py modification (≤25 LOC) + 1 commit.
