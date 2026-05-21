# ENGINE-FALLBACK-COOLDOWN-VIZ — `harness engines cooldowns` verb

## Goal

`state.json::engine_cooldowns` is documented in `dispatch-rules.md` but
operators have no CLI verb to see WHICH engines are currently under
cooldown and when they expire.  Add a small read-only verb so the
operator can answer "why did dispatcher skip Kimi?" without grepping JSON.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New CLI command — `engines` group

Find the existing `engines` block in `src/harness/cli.py` — search for
`@cli.command()` and look for the engines verb (or `@cli.group(name="engines")`).
If it's a single command (no group), promote it to a group; if it's
already a group, add a subcommand.

```python
# If engines is not yet a group, add this group:
@cli.group(name="engines")
def engines_group() -> None:
    """Engine routing + health + cooldown introspection."""
    pass

# Then the existing single-command `engines` becomes a subcommand:
@engines_group.command(name="list")
def engines_list() -> None:
    """Show health for all engines (existing behaviour)."""
    # ...existing body...

# New cooldowns command:
@engines_group.command(name="cooldowns")
def engines_cooldowns() -> None:
    """Show active engine cooldowns (engine_cooldowns from state.json)."""
    from harness.loops.state import read_state
    state_path = Path("coord") / "dev_loop" / "state.json"
    state = read_state(state_path)
    cd = getattr(state, "engine_cooldowns", {}) or {}
    if not cd:
        click.echo("no active cooldowns")
        return
    click.echo(f"{'ENGINE':<24} {'UNTIL':<28}  REASON")
    for engine, info in sorted(cd.items()):
        if isinstance(info, dict):
            until = info.get("until", "-")
            reason = info.get("reason", "-")
        else:
            until = str(info)
            reason = "-"
        click.echo(f"{engine:<24} {until:<28}  {reason}")
```

Important — `engines` MAY already be a single Click command at this point
in cli.py.  If you promote it to a group, the existing default behavior
needs to be preserved as `engines list`.  Use `click.invoke` or split the
underlying function from the decorator so both code paths still work.
The safest minimal change: keep the existing top-level `engines` command
as-is and add a SEPARATE new top-level command `engines-cooldowns`:

```python
@cli.command(name="engines-cooldowns")
def engines_cooldowns() -> None:
    """Show active engine cooldowns."""
    ...
```

Either approach is acceptable.  Pick the one that requires fewer edits.

### 2. Tests

`tests/test_engines_cooldowns_cli.py`:

```python
"""Tests for `harness engines cooldowns` (or engines-cooldowns)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_no_active_cooldowns(runner: CliRunner, tmp_path: Path) -> None:
    """Prints 'no active cooldowns' when state has none."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        # No state.json → read_state returns defaults (no cooldowns)
        result = runner.invoke(cli, ["engines", "cooldowns"])  # or ["engines-cooldowns"]
        # If subcommand layout, this works; if separate command, try the other:
        if result.exit_code != 0:
            result = runner.invoke(cli, ["engines-cooldowns"])
    assert result.exit_code == 0
    assert "no active cooldowns" in result.output


def test_shows_cooldown_entries(runner: CliRunner, tmp_path: Path) -> None:
    """Lists each engine with its until + reason."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        state_path = iso_path / "coord" / "dev_loop" / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "schema_version": 1,
            "loop_status": "armed",
            "tick_count": 0,
            "phase_status": {},
            "engine_cooldowns": {
                "swarm/kimi": {"until": "2099-01-01T00:00:00Z", "reason": "timeout"},
                "swarm/deepseek": {"until": "2099-01-02T00:00:00Z", "reason": "rate_limit"},
            },
        }), encoding="utf-8")
        result = runner.invoke(cli, ["engines", "cooldowns"])
        if result.exit_code != 0:
            result = runner.invoke(cli, ["engines-cooldowns"])
    assert result.exit_code == 0, result.output
    assert "swarm/kimi" in result.output
    assert "swarm/deepseek" in result.output
    assert "timeout" in result.output


def test_handles_string_cooldown_value(runner: CliRunner, tmp_path: Path) -> None:
    """Bare-string cooldown (legacy shape) still prints."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        state_path = iso_path / "coord" / "dev_loop" / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "schema_version": 1,
            "loop_status": "armed",
            "tick_count": 0,
            "phase_status": {},
            "engine_cooldowns": {"swarm/kimi": "2099-01-01T00:00:00Z"},
        }), encoding="utf-8")
        result = runner.invoke(cli, ["engines", "cooldowns"])
        if result.exit_code != 0:
            result = runner.invoke(cli, ["engines-cooldowns"])
    assert result.exit_code == 0
    assert "swarm/kimi" in result.output
```

## Acceptance

- `python -m pytest tests/test_engines_cooldowns_cli.py` — green.
- Full suite stays green.
- `harness engines --help` (or `harness --help`) shows the new verb.

## Constraints

- DO NOT change existing `engines` behavior.
- DO NOT touch `state.py` or `runner.py` — read-only view of an
  existing field.
- Click `isolated_filesystem(temp_dir=tmp_path)` inside tests.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
