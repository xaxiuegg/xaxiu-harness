# Packet: Wave 6/A — Core loop infrastructure (productize coord/dev_loop/)

## Mission

Promote the `coord/dev_loop/` markdown-and-JSON scaffolding to first-class harness code (`src/harness/loops/`) so an autonomous loop can run without a Claude in-session. This is the core: state schema, tick orchestrator, supervisor base class, and one concrete supervisor as the worked example.

Wave 6/B (CLI verb group + Windows Task Scheduler integration) lands separately. This packet is module-only so it can run in parallel with Wave 3 (disjoint file sets).

## In-scope NEW files

- `src/harness/loops/__init__.py` — re-exports
- `src/harness/loops/state.py` — `LoopState` Pydantic model + `read_state(path)` / `write_state(path, state)` atomic helpers. Schema mirrors the current `coord/dev_loop/state.json` structure (loop_status, phase_status, tick_count, last_tick_at, active_dispatches, wave_plan, escalations, engine_slots, phase_cursors). `extra="allow"` for now (the JSON has many free-form fields).
- `src/harness/loops/runner.py` — `tick(state_path, project=None) -> TickResult` that:
  1. Loads state, refuses if `loop_status != "armed"`
  2. Reads observer flags (HIGH/CRITICAL pending) — surfaces but does not modify them (operator-only ack)
  3. Picks eligible phases (`phase_status == "armed"` AND `next_due_at <= now`)
  4. For each eligible phase, runs its supervisor (`supervisors.run_supervisor(phase, state)`)
  5. Merges supervisor diffs in deterministic order (creativity → testing → developing → integrating → process_improvement)
  6. Writes state atomically; appends a structured entry to log.jsonl
  7. Returns `TickResult(phases_acted_on, escalations, next_due_at)`
- `src/harness/loops/supervisors.py` — `BaseSupervisor` ABC + a concrete `TestingSupervisor` (mechanical — runs pytest, parses output, returns diff)
- `tests/test_loops_state.py` — schema + roundtrip + atomic write
- `tests/test_loops_runner.py` — tick happy path + paused-loop short-circuit + observer-flag surfacing + parallelism conflict detection
- `tests/test_loops_supervisors.py` — BaseSupervisor contract + TestingSupervisor smoke

## In-scope MODIFY files

NONE. cli.py + scheduler.py wiring is Wave 6/B.

## Schema (src/harness/loops/state.py)

```python
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class PhaseStatus(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["armed", "paused_by_escalation", "operator_paused"] = "armed"
    last_run_at: str | None = None
    next_due_at: str | None = None

class ActiveDispatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str
    packet: str | None = None
    engine: str
    dispatched_at: str
    wave_id: str | None = None
    timeout_seconds: int = 1200

class WaveEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str = ""
    status: str = "planned"
    depends_on: list[str] = Field(default_factory=list)

class LoopState(BaseModel):
    """Runtime state for an autonomous harness loop.

    Mirrors coord/dev_loop/state.json so the existing prototype data
    loads cleanly into this schema (extra='allow').
    """
    model_config = ConfigDict(extra="allow")
    schema_version: int = 1
    loop_status: Literal["armed", "operator_paused", "exhausted_plan"] = "armed"
    tick_count: int = 0
    last_tick_at: str | None = None
    phase_status: dict[str, str] = Field(default_factory=dict)
    active_dispatches: list[ActiveDispatch] = Field(default_factory=list)
    wave_plan: list[WaveEntry] = Field(default_factory=list)
    escalations: list[dict[str, Any]] = Field(default_factory=list)
    engine_slots: dict[str, Any] = Field(default_factory=dict)
    phase_cursors: dict[str, Any] = Field(default_factory=dict)

def read_state(path: Path) -> LoopState: ...
def write_state(path: Path, state: LoopState) -> None: ...  # atomic
```

## Runner contract (src/harness/loops/runner.py)

```python
from dataclasses import dataclass

@dataclass
class TickResult:
    tick_count: int
    phases_acted_on: list[str]
    state_diff_summary: str
    escalations_raised: list[dict]
    observer_flags_seen: list[str]
    next_due_at: str | None

def tick(
    state_path: Path = Path("coord/dev_loop/state.json"),
    observer_dir: Path = Path("coord/observer"),
    project: str | None = None,
    now: datetime | None = None,
) -> TickResult:
    """Run one tick.

    See coord/dev_loop/manager.md for the procedural contract this
    function implements: Step 0 (observer flags), Step 1-9 (read state,
    check loop_status, classify active dispatches, pick phases, spawn
    supervisors, merge diffs, log, write state, exit).
    """
```

The runner reads observer flags but never deletes them (operator-only ack via `harness observer ack`).

## BaseSupervisor + TestingSupervisor (src/harness/loops/supervisors.py)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SupervisorResult:
    phase: str
    state_diff: dict[str, Any]      # patches to apply to LoopState
    escalation: dict | None = None
    log_summary: str = ""

class BaseSupervisor(ABC):
    phase: str
    @abstractmethod
    def run(self, state: LoopState, *, project: str | None) -> SupervisorResult: ...

class TestingSupervisor(BaseSupervisor):
    """Mechanical supervisor — runs pytest, parses output, no model call.

    First concrete supervisor; demonstrates the BaseSupervisor contract
    end-to-end without depending on engines.dispatcher.  Other
    supervisors (developing, creativity, integrating) come in later
    sub-waves and DO dispatch to engines for judgment work.
    """
    phase = "testing"
    def run(self, state, *, project=None) -> SupervisorResult: ...

def run_supervisor(phase: str, state: LoopState, **kwargs) -> SupervisorResult:
    """Registry-based dispatch.  For v1 only TestingSupervisor is concrete;
    other phases return a no-op SupervisorResult with a "pending Wave 6/B+"
    log_summary so the runner doesn't crash on missing supervisors."""
```

## Tests required

1. **`LoopState` loads existing `coord/dev_loop/state.json`** cleanly (parametrize the test against the real file).
2. **`write_state` is atomic** — mock `os.replace` to fail; original file unchanged.
3. **`tick()` on a paused loop** appends a log entry and returns `phases_acted_on=[]`.
4. **`tick()` with observer HIGH flag pending** surfaces it in `TickResult.observer_flags_seen` and does NOT delete the file.
5. **`tick()` happy path** runs testing supervisor on a fixture, writes state, returns expected `TickResult`.
6. **Parallelism conflict detection** — two phases with overlapping write_sets are not run together (test by setting `phase_status` to fire two phases that touch the same key).
7. **`TestingSupervisor.run()`** mocks pytest (using subprocess.run patched) and returns a SupervisorResult with correct diff.
8. **`run_supervisor("creativity", state)`** returns a no-op SupervisorResult with "pending" in log_summary (so runner doesn't crash).

Target: ≥20 new tests. Suite ≥420.

## Acceptance criteria

1. `python -c "from harness.loops import tick; print(tick.__name__)"` succeeds.
2. `LoopState.model_validate(json.load(open('coord/dev_loop/state.json')))` works.
3. `python -m pytest tests/ -q` shows ≥399 + new tests, all green.
4. Coverage on `src/harness/loops/` ≥75%.
5. Single commit: `feat(loops): core loop infrastructure (Wave 6/A)`.

## Reference

- `coord/dev_loop/state.json` — the file LoopState must round-trip
- `coord/dev_loop/manager.md` — the procedural spec this codifies
- `coord/dev_loop/supervisors/*.md` — prose specs for each supervisor; Wave 6/A implements TestingSupervisor only
- `src/harness/status/store.py` — atomic write reference pattern
- `src/harness/observer/flags.py::list_pending_flags` — for Step 0 observer-flag surfacing

## Output format

5 new files + 0 modifications + 1 commit. cli.py wiring is Wave 6/B.
