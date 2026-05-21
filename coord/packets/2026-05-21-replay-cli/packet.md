# Packet: `harness replay` — decision archaeology for dispatches

## Mission

Add a `harness replay` CLI verb that reconstructs a dispatch's lifecycle from `harness.state.jsonl_log` + `harness.state.db` for forensics. Operator passes a task_id (or dispatch_id) and gets a chronological timeline: engines tried, guards fired, fallback chain, redaction events, latencies, terminal outcome.

This is the creativity-tick idea from 2026-05-20 (score 86/92). Foundation for the dashboard's per-task drill-down view. Per the operator's "full automation until done" directive, ship it to clear the backlog.

## In-scope NEW files

- `src/harness/replay.py` — `replay_dispatch(task_id, jsonl_path=None, db_path=None) -> ReplayReport`; renders timeline string
- `tests/test_replay.py` — fixture jsonl + db, assert timeline correctness

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.command(name="replay")` taking a TASK_ID positional argument. ≤25 LOC.

## Data sources

- `harness.state.jsonl_log` — append-only event log (one line per dispatch outcome / fallback / redaction)
- `harness.state.db` — SQLite history.db with dispatches + fallbacks tables (see `harness.state.db`)

The replay function joins these two sources by `dispatch_id` (the jsonl entries reference a dispatch_id when available; otherwise filter by `project + packet_path`).

## ReplayReport contract

```python
# src/harness/replay.py
from dataclasses import dataclass

@dataclass
class ReplayEvent:
    timestamp: str        # iso8601
    kind: str             # "dispatch_start" | "engine_call" | "guard_fire" | "fallback" | "redaction" | "dispatch_end"
    engine: str | None
    detail: str           # short human-readable description
    latency_ms: int | None = None

@dataclass
class ReplayReport:
    task_id: str
    events: list[ReplayEvent]
    summary: str          # "swarm/kimi -> timeout -> swarm/deepseek -> success"
    total_elapsed_ms: int | None
    final_outcome: str | None

def replay_dispatch(
    task_id: str,
    jsonl_path: Path | None = None,
    db_path: Path | None = None,
) -> ReplayReport: ...

def format_for_human(report: ReplayReport) -> str:
    """Render the report as a multi-line operator-readable timeline."""
```

## CLI surface

```python
@cli.command(name="replay")
@click.argument("task_id")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]), default="pretty")
@click.option("--jsonl-path", type=click.Path(path_type=Path), default=None)
def replay_cmd(task_id: str, fmt: str, jsonl_path: Path | None) -> None:
    """Reconstruct the dispatch lifecycle for TASK_ID."""
    from harness.replay import replay_dispatch, format_for_human
    report = replay_dispatch(task_id, jsonl_path=jsonl_path)
    if fmt == "json":
        import json, dataclasses
        click.echo(json.dumps({
            "task_id": report.task_id,
            "summary": report.summary,
            "total_elapsed_ms": report.total_elapsed_ms,
            "final_outcome": report.final_outcome,
            "events": [dataclasses.asdict(e) for e in report.events],
        }, indent=2))
    else:
        click.echo(format_for_human(report))
```

## Tests required

1. Empty jsonl + empty db → `ReplayReport(task_id, events=[], summary="(no events)")`.
2. Single dispatch_start + dispatch_end → 2 events, summary contains engine name.
3. Multi-engine fallback chain → events in chronological order, summary like "kimi -> timeout -> deepseek -> success".
4. Guard fire event → event with `kind="guard_fire"` and detail referencing the guard.
5. Redaction event → event with `kind="redaction"`, detail mentions field name.
6. `format_for_human` returns multi-line string with timestamps, engine names, latencies.
7. CLI smoke (`replay <id>`) — exit 0, output non-empty.
8. CLI smoke with `--format json` — output parses as JSON with the expected keys.
9. CLI on unknown task_id — exits 0 with "(no events)" message (not an error — operator may be querying an old ID).

Target ≥8 new tests.

## Acceptance criteria

1. `harness replay --help` shows the verb.
2. `harness replay <task_id>` against the actual jsonl/db produces a chronological timeline.
3. `python -m pytest tests/ -q` shows ≥478 + new tests, all green.
4. Single commit: `feat(replay): harness replay CLI verb for dispatch forensics (REPLAY-CLI)`.

## Reference

- `src/harness/state/jsonl_log.py` — event log writer; this packet reads the file
- `src/harness/state/db.py` — SQLite history table; this packet reads dispatches + fallbacks tables
- `src/harness/engines/dispatcher.py` — emits the events being replayed (see `jsonl_log.write_log_entry` calls)
- Memory `user_satisfactory_ux_aspiration` — output should feel like a sim-game replay, holographic-industrial language welcome
- Memory `user_non_technical_role` — keep the pretty output readable without engineering jargon

## Output format

1 new module + 1 new test file + 1 cli.py modification (≤25 LOC) + 1 commit.
