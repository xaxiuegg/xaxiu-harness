# Spec: Status tracker as harness primitive

## Goal

Promote `coord/STATUS.csv` from a hand-maintained operator convention to a first-class harness module + CLI verb group. The status tracker is the **session-failure recovery mechanism**: every dispatch transition writes to it atomically, every session bootstraps from it, every supervisor reads it before deciding next action. A crashed Claude session resumes from STATUS.csv with no lost context.

This is the most load-bearing feature for autonomous-loop resilience — without it, chains corrupt when sessions die.

## Why a primitive, not a convention

The current pattern (this session, warehouse session, others) is "Claude remembers to update STATUS.csv." Failure modes observed:
- Mid-session crash → next session has no record of what was in flight
- Dev manager forgets to update mid-tick → orphan `in_progress` rows
- Multi-process race (Task Scheduler tick + manual session) → CSV corruption
- Hand-edited rows drift from schema → silent data loss

A harness primitive solves all four: Pydantic-validated rows, atomic writes via tempfile+rename, hooks called from the dispatcher (not by the developer), schema-version field for migration.

## Module layout

`src/harness/status/`:
- `__init__.py` — re-exports
- `schema.py` — `StatusRow` Pydantic v2 model (frozen=False since rows mutate); `Status` StrEnum; `Owner` Literal type
- `store.py` — `read_status(path) -> list[StatusRow]`, `write_status(path, rows)` (atomic), `add_row(...)`, `update_row(id, **fields)`, `summary() -> dict[Status,int]`, `verify(path) -> list[ValidationIssue]`
- `hooks.py` — `on_dispatch_start(task_id, wave_id, engine, ...)`, `on_dispatch_complete(task_id, outcome, ...)`, `on_commit(sha, files)` — called by dispatcher + integrating supervisor

## Schema (matches warehouse format + adds machine fields)

```python
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
    effort: str = Field(default="-", max_length=40)  # human-readable; not enforced
    updated: str = Field(default="-", pattern=r"^(\d{4}-\d{2}-\d{2}|-)$")
    notes: str = Field(default="", max_length=1000)
```

## CLI verbs (`harness status` group)

```
harness status init                                         # create coord/STATUS.csv with header row (refuse if exists w/o --force)
harness status add ID CATEGORY TITLE [--status S] [--owner O] [--effort E] [--notes N]
harness status update ID [--status S] [--owner O] [--effort E] [--notes N]
harness status list [--filter STATUS] [--category CAT] [--format pretty|json|csv]
harness status summary                                      # counts by status; "12 shipped, 3 in_progress, ..."
harness status verify                                       # validate schema; flag stuck in_progress (>2× effort)
```

All verbs read the canonical path from `adapter.status_tracking.config.csv_path` if an adapter is loaded; default `coord/STATUS.csv`.

## Atomic-write contract

Every mutation goes through `_atomic_write_csv(path, rows)`:
1. `tempfile.mkstemp(dir=path.parent, prefix=".status_")`
2. Write all rows to temp file with `csv.writer` (NOT pandas — operator wants Excel-compatible)
3. `os.fsync(fd)` before close
4. `os.replace(tmp, path)` (atomic on POSIX + Windows)
5. `os.chmod(path, 0o644)` for operator read access

On any exception during write, the temp file is removed and the original CSV is untouched. No partial writes.

## Hook integration

Modify `src/harness/engines/dispatcher.py::dispatch_packet`:
- After packet validation but before engine call: `hooks.on_dispatch_start(task_id, wave_id, engine, ...)` → adds row with status=`in_progress`
- After engine returns (success or failure): `hooks.on_dispatch_complete(task_id, outcome, ...)` → updates row

Modify `coord/dev_loop/supervisors/integrating.md`:
- After successful commit: invoke `harness status update <wave_id> --status shipped --notes "commit <sha>"`

## mtime canary (recovery-friendly stale detection)

`harness status verify --canary <expected_cadence_minutes>`:
- If `os.path.getmtime(STATUS.csv) < now - 2*cadence_minutes*60` AND any row is `in_progress`, raise `L4.observer.E_STATE_STALE`.
- Used by the observer / process_improvement supervisor every tick.

## Migration from the hand-maintained CSV

Existing `coord/STATUS.csv` (33 rows as of this commit) loads cleanly into the new schema. The `harness status verify` smoke confirms no row has invalid status / regex-violating ID / oversized fields. If any row fails: prompt operator with the diff, do NOT auto-correct.

## Acceptance criteria for the Kimi packet

1. `harness status init` creates `coord/STATUS.csv` with header row, refuses if file exists without `--force`.
2. Existing 33-row STATUS.csv passes `harness status verify` after schema rollout.
3. `harness status add NEW-ID Doc "Some title" --status todo` appends a row; subsequent `harness status list` shows it.
4. `harness status update NEW-ID --status shipped --notes "commit abc1234"` modifies the row + bumps `updated` to today.
5. `harness status summary` prints counts by status (machine-readable + human-readable both supported).
6. Atomic-write contract: kill the process mid-write (mock `os.replace` to raise) — original CSV unchanged.
7. `dispatch_packet` now calls `hooks.on_dispatch_start` / `on_dispatch_complete`; verify a test that dispatches a mock packet sees the corresponding status row appear + update.
8. `python -m pytest tests/ -q` shows 263+ tests + new tests, all green.
9. Single commit per packet: `feat(status): canonical status tracker as harness primitive (#19)`.

## What this unblocks

- True session-crash recovery: new session reads STATUS.csv, knows exactly which rows are `in_progress` and need verification (`git diff`, `parse-swarm-status`, etc).
- Dashboard (Wave 3) reads STATUS.csv as its data source.
- Process-improvement supervisor uses `harness status verify` as its stuck-task detector.
- Wave 6 productization: this primitive is one of the 18 roster rows.
