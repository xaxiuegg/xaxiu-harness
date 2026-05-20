# Packet: Independent observer primitive (roster #20)

## Mission

Implement `src/harness/observer/` module + `harness observer` CLI verb group + Task Scheduler integration per `spec/observer.md`. The observer is the check on dev-manager authority — it runs independently, audits via cross-engine dispatch, writes HIGH_FLAG_PENDING.md when concerned, and forces the dev manager to read flags at the start of every tick.

This is roster row #20 — the "who watches the watcher?" answer. Dispatch AFTER row #19 (status-tracker) lands because the observer reads STATUS.csv schema-validated rows.

## In-scope NEW files

- `src/harness/observer/__init__.py` — re-exports
- `src/harness/observer/flags.py` — `FlagSeverity` StrEnum (LOW/MED/HIGH/CRITICAL) + `Flag` Pydantic model + `FlagStore` helpers
- `src/harness/observer/cycle.py` — `run_cycle(engine, audit_window_minutes) -> CycleReport`; reads log.jsonl + STATUS.csv + recent commits, dispatches cross-engine audit, parses findings
- `src/harness/observer/audit_prompt.py` — `build_audit_prompt(context) -> str`; templated prompt the audit engine receives
- `src/harness/observer/scheduler.py` — `register_tasks(cadence_minutes, daily_time)` + `unregister_tasks()` using PowerShell `Register-ScheduledTask`
- `tests/test_observer.py` — smoke tests for each piece

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group() def observer()` + 8 subcommands (`init`, `arm`, `disarm`, `pause`, `resume`, `cycle-now`, `status`, `flags`, `ack`)
- `coord/dev_loop/manager.md` — add step 0: "Check coord/observer/HIGH_FLAG_PENDING.md as first action of every tick"

## Schema

```python
# src/harness/observer/flags.py
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

class FlagSeverity(StrEnum):
    LOW = "low"
    MED = "med"
    HIGH = "high"
    CRITICAL = "critical"

class Flag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, pattern=r"^FLAG-\d{4}-\d{2}-\d{2}-\d+$")
    severity: FlagSeverity
    category: str           # "authority_overreach" | "scope_creep" | "engine_routing" | "status_drift" | "L5_discipline" | "cost_burn" | "memory_consistency"
    summary: str            # one-line
    detail: str             # multi-paragraph rationale + evidence
    evidence: list[str]     # file paths, log entries, commit shas
    raised_at: str          # iso8601
    cycle_id: str           # the cycle that raised it
    acknowledged: bool = False
    acknowledged_at: str | None = None
    acknowledged_by: str | None = None  # "operator" only
```

## Cycle runner

```python
# src/harness/observer/cycle.py
def run_cycle(engine: str = "swarm/deepseek", audit_window_minutes: int = 60) -> CycleReport:
    """Run one observer cycle.

    1. Gather context: last N log.jsonl entries, STATUS.csv diff vs last cycle, last 10 commits.
    2. Build audit prompt via audit_prompt.build_audit_prompt(context).
    3. Dispatch to engine via xaxiu-swarm dispatch (or in-process for testing).
    4. Parse engine response into list[Flag].
    5. Write cycle report to coord/observer/cycles/observer_<iso8601>.md.
    6. For each HIGH flag: write/append coord/observer/HIGH_FLAG_PENDING.md.
    7. For CRITICAL: also write coord/observer/CRITICAL_FLAG_PENDING.md.
    8. Return CycleReport(cycle_id, flags, engine_used, elapsed_s).
    """
```

The dispatch happens via the existing `harness.engines.dispatcher.dispatch_packet` — observer is a regular client of the dispatcher, just uses a different backend than the dev manager.

## CLI integration

```python
# in src/harness/cli.py
@cli.group()
def observer() -> None:
    """Independent meta-audit observer (the check on dev-manager authority)."""

@observer.command(name="init")
def observer_init() -> None: ...

@observer.command(name="arm")
@click.option("--cadence-minutes", default=60, type=int)
def observer_arm(cadence_minutes: int) -> None: ...

@observer.command(name="disarm")
def observer_disarm() -> None: ...

@observer.command(name="pause")
def observer_pause() -> None: ...

@observer.command(name="resume")
def observer_resume() -> None: ...

@observer.command(name="cycle-now")
@click.option("--engine", default="swarm/deepseek")
def observer_cycle_now(engine: str) -> None: ...

@observer.command(name="status")
def observer_status() -> None: ...

@observer.command(name="flags")
@click.option("--severity", type=click.Choice(["low","med","high","critical"]))
@click.option("--clear", help="Flag ID to clear")
def observer_flags(severity: str | None, clear: str | None) -> None: ...

@observer.command(name="ack")
@click.argument("finding_id")
def observer_ack(finding_id: str) -> None: ...  # marks flag acknowledged=True; operator-only check
```

## manager.md modification

Insert as new section "Step 0" before the existing tick procedure:

```markdown
## Step 0 — Read HIGH_FLAG_PENDING (FIRST ACTION OF EVERY TICK)

Before any other work in a tick:

1. Check `coord/observer/HIGH_FLAG_PENDING.md`. If exists:
   - Read it; parse the Flag JSON header
   - Surface findings at the top of the dev manager's response
   - If operator is present: pause and await `harness observer ack <id>` (or operator chat ack)
   - If running autonomous (Task Scheduler tick): mark seen in coord/observer/seen.log; proceed
   - Move file to coord/observer/cycles/handled/HIGH_FLAG_<id>.md
2. Check `coord/observer/CRITICAL_FLAG_PENDING.md`. If exists:
   - HALT all autonomous work
   - Surface to operator with full diagnostic
   - Do not proceed until `harness observer ack <id>` from operator

Only after step 0 completes does the tick procedure (read state.json, check active dispatches, etc.) continue.
```

## Acceptance criteria

1. `harness observer init` creates `coord/observer/` tree.
2. `harness observer arm --cadence-minutes 60` registers `XaxiuHarnessObserverCycle` (hourly) + `XaxiuHarnessObserverDailyRetro` (23:00).
3. `harness observer cycle-now --engine swarm/deepseek` runs end-to-end against current log.jsonl + STATUS.csv.
4. Forced HIGH scenario: insert a mock log entry containing `swarm/claude` dispatch; run cycle; verify HIGH_FLAG_PENDING.md is created.
5. `coord/dev_loop/manager.md` step 0 documented.
6. `python -m pytest tests/ -q` shows ≥285 tests, all green.
7. Single commit: `feat(observer): independent harness observer (#20)`.

## Reference

- `spec/observer.md` — full spec
- `D:/Projects/warehouse/dev-panel-runs/ag-qty-bug-v101/observer/` — pattern source (READ-ONLY)
- `src/harness/status/` — sibling primitive (row #19); observer reads STATUS.csv via this module
- `src/harness/errors.py::ConfigCorruption` — raised if observer-state.json is corrupt
- `bin/register-dev-loop-task.ps1` — pattern for Task Scheduler registration

## Output format

6 new files + 2 modifications + 1 commit. Acceptance gated by HIGH-flag scenario reproducing the interrupt protocol end-to-end.
