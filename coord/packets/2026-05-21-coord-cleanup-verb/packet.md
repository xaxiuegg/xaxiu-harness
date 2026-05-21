# Packet: `harness coord cleanup` — worktree + run garbage collection

## Mission

After v2/D shipped, every `harness coord run` leaves a worktree directory at `.harness/worktrees/<run_id>/<worker-id>/` and a run-state directory at `.harness/runs/<run_id>/`. Currently nothing cleans these up — completed runs accumulate forever. Add `harness coord cleanup` to remove worktrees + run-state for completed runs (configurable).

## In-scope NEW files

- `tests/test_coord_cleanup.py` — happy-path + dry-run + skip-active tests

## In-scope MODIFY files

- `src/harness/coord/coordinator.py` — add `cleanup_run(run_id, ...)` + `cleanup_all_completed(...)` functions
- `src/harness/cli.py` — add `@coord.command(name="cleanup")` subcommand with options:
  - `--run-id <id>`: clean one specific run; default = all completed
  - `--dry-run`: list what would be removed without removing
  - `--keep-deliverables`: preserve runs/<id>/deliverables/ + plan.json (audit trail), only remove worktrees + checkpoints
  - `--force`: skip the "are you sure" prompt (tests use this)

## API contract (src/harness/coord/coordinator.py)

```python
@dataclass
class CleanupReport:
    runs_removed: list[str]
    worktrees_removed: list[str]
    bytes_freed: int
    skipped_active: list[str]
    dry_run: bool

def cleanup_run(
    run_id: str,
    *,
    repo_root: Path | None = None,
    keep_deliverables: bool = False,
    dry_run: bool = False,
) -> CleanupReport: ...

def cleanup_all_completed(
    *,
    repo_root: Path | None = None,
    keep_deliverables: bool = False,
    dry_run: bool = False,
) -> CleanupReport:
    """Iterate runs/, classify each run.json by state, remove completed/failed
    runs. NEVER remove a run with state in {planning, running, integrating}.
    """
```

Removes:
- `.harness/worktrees/<run_id>/` (whole tree)
- `.harness/runs/<run_id>/checkpoints/` (always)
- `.harness/runs/<run_id>/deliverables/` (unless `keep_deliverables=True`)
- `.harness/runs/<run_id>/run.json` + `plan.json` (unless `keep_deliverables=True`)

For each worktree removed: `git worktree remove <path> --force` (mirrors `harness.coord.worktree.remove_worktree`).

## CLI

```python
@coord_group.command(name="cleanup")
@click.option("--run-id", default=None, help="Specific run; default = all completed")
@click.option("--dry-run", is_flag=True)
@click.option("--keep-deliverables", is_flag=True,
              help="Preserve plan.json + deliverables/; remove only worktrees + checkpoints")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def coord_cleanup(run_id, dry_run, keep_deliverables, force):
    """Remove worktrees + run-state for completed runs."""
    from harness.coord.coordinator import cleanup_run, cleanup_all_completed

    if not force and not dry_run:
        if not click.confirm("Remove worktrees + run state? Cannot be undone."):
            click.echo("aborted")
            sys.exit(0)

    if run_id:
        report = cleanup_run(run_id, keep_deliverables=keep_deliverables, dry_run=dry_run)
    else:
        report = cleanup_all_completed(keep_deliverables=keep_deliverables, dry_run=dry_run)

    if dry_run:
        click.echo("DRY RUN — nothing actually removed")
    click.echo(f"runs cleared: {len(report.runs_removed)}")
    click.echo(f"worktrees removed: {len(report.worktrees_removed)}")
    click.echo(f"bytes freed: {report.bytes_freed:,}")
    if report.skipped_active:
        click.echo(f"skipped active runs: {', '.join(report.skipped_active)}")
```

## Tests required

1. `cleanup_run` removes worktree + run.json for a fake completed run (mock filesystem).
2. `cleanup_run` skips when run state is `running` or `integrating` (logs to skipped_active).
3. `cleanup_all_completed` iterates runs/ and only removes completed.
4. `keep_deliverables=True` preserves plan.json + deliverables/.
5. `dry_run=True` returns report but removes nothing from disk.
6. `bytes_freed` is non-zero after a real removal.
7. CLI smoke (`harness coord cleanup --dry-run --force`) exits 0.
8. CLI without `--force` and stdin closed exits without removing (confirmation path).

Target ≥7 new tests.

## Acceptance criteria

1. `harness coord cleanup --help` shows the new subcommand.
2. `harness coord cleanup --dry-run --force` against the actual repo prints a report without touching the filesystem.
3. `python -m pytest tests/ -q` shows green.
4. Single commit: `feat(coord): harness coord cleanup verb for worktree + run-state GC`.

## Reference

- `spec/multi-agent-harness-architecture.md` §3.1 — Coordinator stores under `.harness/runs/` + `.harness/worktrees/`
- `src/harness/coord/worktree.py::remove_worktree` — pattern for git worktree removal
- `src/harness/coord/run_state.py` — RunState read/write
- `src/harness/coord/coordinator.py` — sibling module

## Output format

1 new test file + 2 file mods (coordinator.py + cli.py) + 1 commit.
