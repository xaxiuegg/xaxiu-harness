# wave3-coord-engines-list — `harness engines --json` machine-readable output

## Context

`harness engines` prints a human-readable summary of engine health.
Dashboards want a JSON variant.

## Goal

Add `--json` flag to `harness engines` that emits each engine's:
- `name`, `priority` (HIGH/NORMAL/AVOID), `status` (up/degraded/down),
  `last_fail` (ISO or null), `cooldown_until` (ISO or null).

When `--json` set, exit 0 with the JSON list on stdout.  No human text.

## Acceptance

- Existing `tests/test_engines_cooldowns_cli.py` stays green.
- 2 new tests via CliRunner cover JSON output happy path + empty health.
- Human-readable output preserved when `--json` omitted.

## File scope

- `src/harness/cli.py` — extend `engines` click command.  ~20 LOC.
- `tests/test_engines_cooldowns_cli.py` — append 2 tests.

## Read-set — byte-exact

### src/harness/cli.py (engines command region)
```python
@cli.command(name="engines")
def engines_cmd() -> None:
    """Show engine status, priority, and cooldown."""
    from harness.state import files as state_files
    health = state_files.read_engine_health()
    for name in ["deepseek", "kimi", "anthropic", "gemini", "mimo"]:
        h = health.get(name)
        status = h.status if h else "up"
        priority = h.priority if h else "NORMAL"
        last_fail = h.last_fail if h else None
        cooldown = h.cooldown_until if h else None
        click.echo(f"{name:12} {priority:6} {status:9} "
                   f"last_fail={last_fail or '-':<26} cooldown={cooldown or '-'}")
```

DO NOT add a new engine to the list.  DO NOT touch state_files internals.
