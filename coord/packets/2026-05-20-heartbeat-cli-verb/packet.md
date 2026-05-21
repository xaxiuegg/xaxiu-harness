# Packet: `harness heartbeat` CLI verb (passive operator status)

## Mission

Add a passive heartbeat primitive so the operator can answer "is the dev manager alive? are loops idle?" in one second without scrolling chat history. The dev manager pulses to `coord/dev_loop/heartbeat.json` every tick; `harness heartbeat show` reads the file and reports lag + activity summary.

This is roster row #17 (continuous heartbeat). Pairs with `harness state inspect` (roster #18-adjacent backlog) — both are non-technical-operator-readable status surfaces.

## In-scope NEW files

- `src/harness/heartbeat.py` — module with `pulse(state_path)` / `read_heartbeat(path)` / `format_for_human(beat)` helpers
- `tests/test_heartbeat.py` — schema + roundtrip + lag-calculation + CLI smoke tests

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group() def heartbeat()` with two subcommands (`pulse`, `show`). Keep the cli.py footprint minimal: ≤30 LOC of additions; bulk logic lives in `heartbeat.py`.

## Heartbeat schema

```python
# src/harness/heartbeat.py
from pathlib import Path
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field
import json
import tempfile
import os

class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pulsed_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
    tick_count: int = Field(ge=0)
    loop_status: str           # mirrors state.json::loop_status
    active_dispatches: int = Field(ge=0)
    in_flight_kimi: int = Field(ge=0)
    in_flight_deepseek: int = Field(ge=0)
    phase_statuses: dict[str, str]
    last_escalation_id: str | None = None

HEARTBEAT_PATH = Path("coord/dev_loop/heartbeat.json")
```

## Module API

```python
def pulse(state_path: Path = Path("coord/dev_loop/state.json"),
          heartbeat_path: Path = HEARTBEAT_PATH) -> Heartbeat:
    """Read state.json, derive a Heartbeat, write atomically to heartbeat_path."""

def read_heartbeat(heartbeat_path: Path = HEARTBEAT_PATH) -> Heartbeat | None:
    """Load + validate; return None if file missing."""

def format_for_human(beat: Heartbeat | None,
                     now: datetime | None = None) -> str:
    """Render as a 3-5 line operator-readable summary, e.g.:

      Heartbeat: 42s ago (tick #11, status armed)
      Dispatches: 1 active (1 kimi, 0 deepseek)
      Phases: creativity armed, developing armed, testing armed, integrating armed, process_improvement armed
      No active escalations.
    """
```

Atomic-write contract: same `tempfile.mkstemp` + `os.replace` pattern as `harness.status.store` (or `harness.state.files._save_data`). Never partial-write.

## CLI verbs

```python
# in src/harness/cli.py
@cli.group()
def heartbeat() -> None:
    """Passive dev-manager liveness signal for the operator."""

@heartbeat.command(name="pulse")
def heartbeat_pulse() -> None:
    """Emit one heartbeat now (called by the dev-loop manager each tick)."""
    from harness.heartbeat import pulse
    beat = pulse()
    click.echo(f"pulsed at {beat.pulsed_at} (tick #{beat.tick_count})")

@heartbeat.command(name="show")
def heartbeat_show() -> None:
    """Print the last heartbeat in operator-readable form."""
    from harness.heartbeat import read_heartbeat, format_for_human
    click.echo(format_for_human(read_heartbeat()))
```

## Tests required

1. `pulse()` writes a valid Heartbeat that roundtrips via `read_heartbeat()`.
2. `pulse()` against a missing state.json raises a `HarnessError` (L4.config) — never a silent no-op.
3. Atomic-write: mock `os.replace` to raise; assert original file unchanged.
4. `format_for_human(None)` returns "Heartbeat: never (no pulse recorded)".
5. `format_for_human(beat)` with a stale beat (>2× cadence) prepends "⚠ STALE — ".
6. `harness heartbeat pulse` smoke via CliRunner: exit 0, prints timestamp.
7. `harness heartbeat show` smoke: exit 0, output matches a multi-line summary regex.

## Acceptance criteria

1. `harness heartbeat --help` shows `pulse` and `show`.
2. After `harness heartbeat pulse`, `coord/dev_loop/heartbeat.json` exists and validates against the `Heartbeat` schema.
3. `harness heartbeat show` after a pulse renders the operator-readable summary within 1 second.
4. `python -m pytest tests/ -q` shows ≥263 + 7 new tests, all green.
5. Single commit: `feat(heartbeat): passive dev-manager liveness signal (HEARTBEAT)`.

## Reference

- `coord/dev_loop/state.json` — source of truth this heartbeat summarizes
- `spec/session-derived-feature-roster.md` row #17 — origin directive
- `src/harness/state/files.py::_save_data` — atomic-write reference pattern
- `src/harness/status/store.py` (post-#19) — sibling atomic-write pattern; reuse the same helper if available
- Memory `feedback_active_tracking_table` — mtime canary, two-line litmus

## Output format

1 new module + 1 new test file + 1 cli.py modification (≤30 LOC) + 1 commit.
