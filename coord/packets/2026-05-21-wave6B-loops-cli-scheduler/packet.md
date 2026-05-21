# Packet: Wave 6/B — `harness loop` CLI verb group + Task Scheduler

## Mission

Surface the Wave 6/A core (`src/harness/loops/`) through CLI + Windows Task Scheduler integration. Operator can `harness loop init` once per project and `harness loop start --cadence-minutes 30` to register the runner. Completes the loop-productization story.

Depends on Wave 6/A landing first.

## In-scope NEW files

- `src/harness/loops/scheduler.py` — `register_loop_task(cadence_minutes)` + `unregister_loop_task()` mirroring `harness.observer.scheduler.register_tasks`
- `tests/test_loops_cli.py` — CLI smoke
- `tests/test_loops_scheduler.py` — scheduler register/unregister smoke (mocked subprocess for Register-ScheduledTask)

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group(name="loop")` with subcommands: `init`, `tick`, `start`, `stop`, `status`. Keep cli.py footprint minimal: ≤40 LOC, delegate logic to `harness.loops`.

## CLI surface

```
harness loop init [--state-path PATH]   # create coord/dev_loop/state.json from defaults if missing
harness loop tick [--state-path PATH]   # run ONE tick (calls harness.loops.tick)
harness loop start [--cadence-minutes N]  # register Task Scheduler entry HarnessLoopTick that runs `harness loop tick`
harness loop stop                       # unregister Task Scheduler entry
harness loop status [--state-path PATH] # print loop_status + tick_count + last_tick_at + next_due
```

## Scheduler module (src/harness/loops/scheduler.py)

```python
def register_loop_task(
    cadence_minutes: int = 30,
    task_name: str = "HarnessLoopTick",
) -> tuple[bool, str]:
    """Register a Windows Task Scheduler entry to run `harness loop tick`
    every `cadence_minutes` minutes.  Returns (ok, message)."""

def unregister_loop_task(task_name: str = "HarnessLoopTick") -> tuple[bool, str]:
    """Unregister the loop tick task."""

def is_registered(task_name: str = "HarnessLoopTick") -> bool: ...
```

Same PowerShell `Register-ScheduledTask` pattern as `harness.observer.scheduler` (already shipped in Wave 5/6).

## CLI implementations

```python
@cli.group(name="loop")
def loop_group() -> None:
    """Autonomous dev loop — productized coord/dev_loop/ scaffolding."""

@loop_group.command(name="init")
@click.option("--state-path", type=click.Path(path_type=Path),
              default=Path("coord/dev_loop/state.json"))
def loop_init(state_path: Path) -> None:
    """Create coord/dev_loop/state.json if missing."""
    from harness.loops.state import LoopState, write_state
    if state_path.exists():
        click.echo(f"already exists: {state_path}")
        sys.exit(0)
    write_state(state_path, LoopState())
    click.echo(f"created {state_path}")

@loop_group.command(name="tick")
@click.option("--state-path", type=click.Path(path_type=Path),
              default=Path("coord/dev_loop/state.json"))
def loop_tick(state_path: Path) -> None:
    """Run one tick of the autonomous loop."""
    from harness.loops.runner import tick as _tick
    result = _tick(state_path=state_path)
    click.echo(
        f"tick #{result.tick_count} phases={','.join(result.phases_acted_on) or '(none)'} "
        f"next={result.next_due_at or '-'}"
    )

@loop_group.command(name="start")
@click.option("--cadence-minutes", type=int, default=30)
def loop_start(cadence_minutes: int) -> None: ...

@loop_group.command(name="stop")
def loop_stop() -> None: ...

@loop_group.command(name="status")
@click.option("--state-path", type=click.Path(path_type=Path),
              default=Path("coord/dev_loop/state.json"))
def loop_status(state_path: Path) -> None: ...
```

## Tests required

1. `harness loop init` creates state.json with defaults.
2. `harness loop init` on existing file is idempotent.
3. `harness loop tick` against a fixture state.json runs the testing supervisor + writes state.
4. `harness loop status` prints loop_status + tick_count.
5. `register_loop_task` smoke (mocked subprocess) returns (True, msg).
6. `unregister_loop_task` smoke (mocked).
7. `is_registered` returns expected bool for present/absent task (mocked).

Target ≥10 new tests.

## Acceptance criteria

1. `harness loop --help` lists 5 subcommands.
2. `harness loop tick` against the live `coord/dev_loop/state.json` executes a tick and increments `tick_count`.
3. `harness loop start --cadence-minutes 30` registers a Windows Task Scheduler entry (smoke-tested manually by operator post-merge).
4. `python -m pytest tests/ -q` shows ≥420 + new tests, all green.
5. Single commit: `feat(loops): harness loop CLI verb group + scheduler (Wave 6/B)`.

## Reference

- Wave 6/A code in `src/harness/loops/state.py`, `runner.py`, `supervisors.py` — sibling primitives this packet wires to the CLI
- `src/harness/observer/scheduler.py` — pattern reference for Task Scheduler integration
- `coord/dev_loop/manager.md` — procedural spec the productization mirrors

## Output format

3 new files + 1 cli.py modification (≤40 LOC) + 1 commit.
