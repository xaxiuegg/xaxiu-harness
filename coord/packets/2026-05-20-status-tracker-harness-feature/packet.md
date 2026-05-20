# Packet: Status tracker as harness primitive (roster #19)

## Mission

Implement `src/harness/status/` module + `harness status` CLI verb group per `spec/status-tracker.md`. The status tracker becomes a first-class harness primitive (not a hand-maintained convention) so session crashes never corrupt the chain. This is the recovery layer for autonomous loops.

**Highest-priority feature** of this dispatch round. Dispatch BEFORE Wave 5/A + 5/B because everything else depends on STATUS.csv discipline.

## In-scope NEW files

- `src/harness/status/__init__.py` — re-exports
- `src/harness/status/schema.py` — `Status` StrEnum + `StatusRow` Pydantic v2 model
- `src/harness/status/store.py` — read/write/add/update/summary/verify; atomic via tempfile+rename
- `src/harness/status/hooks.py` — `on_dispatch_start`, `on_dispatch_complete`, `on_commit`
- `tests/test_status.py` — schema + atomic-write + roundtrip + verify-canary + dispatcher-hook tests

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group() def status()` + 5 subcommands (`init`, `add`, `update`, `list`, `summary`)
- `src/harness/engines/dispatcher.py` — call `harness.status.hooks.on_dispatch_start` / `on_dispatch_complete` from `dispatch_packet`
- Existing `coord/STATUS.csv` — leave content unchanged; verify it loads cleanly against the new schema

## Schema (match the spec exactly)

```python
# src/harness/status/schema.py
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

class Status(StrEnum):
    SHIPPED = "shipped"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"
    TODO = "todo"
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    PARTIAL = "partial"
    PROPOSED = "proposed"
    PARKED = "parked"
    SPEC_DONE = "spec-done"
    DESIGN_DONE = "design-done"
    PLANNED = "planned"

class StatusRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9][A-Z0-9_/-]*$")
    category: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    status: Status
    owner: str = Field(min_length=1, max_length=80)
    effort: str = Field(default="-", max_length=40)
    updated: str = Field(default="-", pattern=r"^(\d{4}-\d{2}-\d{2}|-)$")
    notes: str = Field(default="", max_length=1000)
```

## Store contract

```python
# src/harness/status/store.py
def read_status(path: Path) -> list[StatusRow]: ...
def write_status(path: Path, rows: list[StatusRow]) -> None: ...  # atomic
def add_row(path: Path, row: StatusRow) -> None: ...
def update_row(path: Path, row_id: str, **fields) -> StatusRow: ...
def summary(path: Path) -> dict[Status, int]: ...
def verify(path: Path, expected_cadence_minutes: int | None = None) -> list[str]: ...
```

Atomic write: `tempfile.mkstemp(dir=path.parent, prefix=".status_")`, csv.writer, fsync, os.replace, chmod 0o644. On any exception during write, remove temp and leave original intact. Single test verifies this by mocking `os.replace` to raise.

## CLI verb group

```python
# in src/harness/cli.py
@cli.group()
def status() -> None:
    """Manage the canonical STATUS.csv task tracker."""

@status.command(name="init")
@click.option("--force", is_flag=True)
def status_init(force: bool) -> None: ...  # create coord/STATUS.csv w/ header; refuse if exists w/o --force

@status.command(name="add")
@click.argument("id_")
@click.argument("category")
@click.argument("title")
@click.option("--status", "status_", type=click.Choice([s.value for s in Status]), default="todo")
@click.option("--owner", default="Claude")
@click.option("--effort", default="-")
@click.option("--notes", default="")
def status_add(...): ...

@status.command(name="update")
@click.argument("id_")
@click.option("--status", "status_", type=click.Choice([s.value for s in Status]))
@click.option("--owner")
@click.option("--effort")
@click.option("--notes")
def status_update(id_, status_, owner, effort, notes): ...  # automatically bumps `updated` to today

@status.command(name="list")
@click.option("--filter", "filter_", type=click.Choice([s.value for s in Status]))
@click.option("--category")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json", "csv"]), default="pretty")
def status_list(...): ...

@status.command(name="summary")
def status_summary() -> None: ...  # prints "12 shipped, 3 in_progress, 5 queued, ..."
```

## Hook integration (dispatcher.py)

```python
# In dispatch_packet, after entry validation:
try:
    from harness.status import hooks as status_hooks
    status_hooks.on_dispatch_start(task_id=..., wave_id=..., engine=...)
except Exception:
    pass  # never let status-tracker bookkeeping break dispatch

# After engine returns (success or failure path), before final return:
try:
    status_hooks.on_dispatch_complete(task_id=..., outcome=..., commit_sha=None)
except Exception:
    pass
```

The wrapping `try/except` is critical — status-tracker MUST NOT raise exceptions into dispatch_packet (which has a never-raises contract per its docstring).

## Tests required

- Schema rejects: blank id, lowercase id, oversized fields, unknown status enum, malformed updated date.
- Existing `coord/STATUS.csv` loads cleanly: parametrize `read_status("coord/STATUS.csv")` and assert all 33+ rows valid.
- Roundtrip: `write_status(tmp_path, rows)` then `read_status(tmp_path)` returns equal rows.
- Atomic-write: mock `os.replace` to raise; verify original file unchanged + temp removed.
- `update_row("NONEXISTENT", ...)` raises `KeyError`.
- `summary()` returns correct counts for the test fixture.
- `verify(path, expected_cadence_minutes=60)` flags stale + stuck rows.
- CLI smoke: `harness status init` + `add` + `update` + `list` + `summary` via `click.testing.CliRunner`.
- Dispatcher hook integration: mock dispatch_packet's engine call, verify status row appears with `in_progress` then updates to `shipped` (or `failed`).

Target ≥285 tests total (was 263; +22 new).

## Acceptance criteria

1. `harness status --help` shows the 5 subcommands.
2. `harness status verify` against the existing `coord/STATUS.csv` reports zero issues.
3. `harness status add TEST-001 Doc "Test row" --status todo` appends + persists.
4. `harness status update TEST-001 --status shipped --notes "smoke"` modifies + bumps `updated`.
5. `harness status summary` prints counts in both pretty + raw forms.
6. `python -m pytest tests/ -q` shows ≥285 passed.
7. Single commit: `feat(status): canonical STATUS tracker as harness primitive (#19)`.

## Reference

- `spec/status-tracker.md` — full spec
- `coord/STATUS.csv` — existing 33-row fixture (must still load after schema rollout)
- Memory `feedback_status_csv_canonical` — operator directive that drove this
- Memory `feedback_active_tracking_table` — mtime canary, two-line litmus
- `src/harness/adapters/schema.py` — pattern reference for Pydantic v2 models
- `src/harness/state/files.py::_save_data` — pattern reference for atomic-write helper

## Output format

5 new files + 2 modifications + 1 commit. No changes to existing `coord/STATUS.csv` content.
