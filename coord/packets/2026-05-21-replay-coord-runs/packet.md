# REPLAY-COORD-RUNS — extend `harness replay` to surface v2 coord runs

## Goal

`harness replay <task_id>` reconstructs a single dispatch's lifecycle
from history.db + jsonl.  Extend it to also accept a coord run_id and
reconstruct the full v2 run (planner output, per-worker checkpoints,
worker progress, integrator notify).

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. Helper in `src/harness/replay.py`

ADD a new public helper next to the existing `replay_dispatch` (do not
modify `replay_dispatch` or `format_for_human`):

```python
@dataclasses.dataclass
class CoordRunReport:
    """Reconstructed lifecycle for one v2 coord run."""
    run_id: str
    state: str
    spec_path: str
    workers: list[dict]
    progress: list[dict]
    notify: dict | None
    total_events: int


def replay_coord_run(run_id: str, *, runs_dir: Path | None = None) -> CoordRunReport:
    """Reconstruct one v2 coord run from its on-disk artifacts.

    Reads runs/<run_id>/{run_state.json, plan.json, checkpoints/*, notify.json}
    and folds them into a single report ordered by per-step timestamp.
    """
    base = Path(runs_dir) if runs_dir else Path("runs")
    run_dir = base / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"no such run {run_dir}")

    def _load_json(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    run_state = _load_json(run_dir / "run_state.json")
    plan = _load_json(run_dir / "plan.json")
    notify = _load_json(run_dir / "notify.json") or None

    workers: list[dict] = []
    progress: list[dict] = []
    ckpt_dir = run_dir / "checkpoints"
    if ckpt_dir.exists():
        for p in sorted(ckpt_dir.glob("*.json")):
            data = _load_json(p)
            if data:
                workers.append(data)
        for p in sorted(ckpt_dir.glob("*.progress.jsonl")):
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ev["_worker_id"] = p.stem.replace(".progress", "")
                    progress.append(ev)
            except OSError:
                continue
    progress.sort(key=lambda e: e.get("ts", ""))

    return CoordRunReport(
        run_id=run_id,
        state=str(run_state.get("state", "unknown")),
        spec_path=str(plan.get("spec_path", "")),
        workers=workers,
        progress=progress,
        notify=notify,
        total_events=len(progress),
    )


def format_coord_for_human(report: CoordRunReport) -> str:
    lines: list[str] = []
    lines.append(f"run {report.run_id} (state: {report.state})")
    lines.append(f"  spec: {report.spec_path}")
    lines.append(f"  workers: {len(report.workers)}")
    for w in report.workers:
        wid = w.get("worker_id", "?")
        state = w.get("state", "?")
        sha = w.get("commit_sha") or "—"
        lines.append(f"    {wid}: {state}  commit={sha}")
    lines.append(f"  progress events: {report.total_events}")
    if report.notify:
        lines.append(f"  notify: success={report.notify.get('success')} commit={report.notify.get('commit_sha')}")
    return "\n".join(lines)
```

(Add `import dataclasses` to the top of replay.py if not already there.)

### 2. Extend the CLI `harness replay` to dispatch by id pattern

In `src/harness/cli.py`, find `@cli.command(name="replay")` (around line
1055).  Modify the existing `replay_cmd` to detect whether `task_id`
looks like a v2 run_id (matches `^\d{8}T\d{6}-[a-z0-9]{4}$`) and route
to the new helper:

```python
@cli.command(name="replay")
@click.argument("task_id")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]), default="pretty")
@click.option("--jsonl-path", type=click.Path(path_type=Path), default=None)
def replay_cmd(task_id: str, fmt: str, jsonl_path: Path | None) -> None:
    """Reconstruct the dispatch (or v2 coord run) lifecycle for TASK_ID."""
    import dataclasses, re
    from harness.replay import (
        replay_dispatch, format_for_human,
        replay_coord_run, format_coord_for_human,
    )

    is_run_id = bool(re.match(r"^\d{8}T\d{6}-[a-z0-9]{4}$", task_id))
    if is_run_id:
        try:
            crep = replay_coord_run(task_id)
        except FileNotFoundError as exc:
            click.echo(f"error: {exc}", err=True)
            sys.exit(1)
        if fmt == "json":
            click.echo(json.dumps(dataclasses.asdict(crep), indent=2, default=str))
        else:
            click.echo(format_coord_for_human(crep))
        return

    report = replay_dispatch(task_id, jsonl_path=jsonl_path)
    if fmt == "json":
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

### 3. Tests

`tests/test_replay_coord_runs.py`:

```python
"""Tests for REPLAY-COORD-RUNS — replay_coord_run + CLI routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.replay import replay_coord_run, format_coord_for_human


def _seed_run(base: Path, run_id: str) -> Path:
    run_dir = base / "runs" / run_id
    (run_dir / "checkpoints").mkdir(parents=True)
    (run_dir / "run_state.json").write_text(json.dumps({
        "state": "completed", "run_id": run_id,
    }), encoding="utf-8")
    (run_dir / "plan.json").write_text(json.dumps({
        "spec_path": "spec.md", "tasks": [{"worker_id": "worker-1"}],
    }), encoding="utf-8")
    (run_dir / "checkpoints" / "worker-1.json").write_text(json.dumps({
        "worker_id": "worker-1", "state": "completed",
        "commit_sha": "abc1234", "files_modified": ["x.txt"],
    }), encoding="utf-8")
    (run_dir / "checkpoints" / "worker-1.progress.jsonl").write_text(
        '\n'.join([
            json.dumps({"ts": "2026-05-21T01:00:00Z", "event": "step_start", "step_id": "s1"}),
            json.dumps({"ts": "2026-05-21T01:00:05Z", "event": "step_done", "step_id": "s1"}),
        ]) + "\n",
        encoding="utf-8",
    )
    (run_dir / "notify.json").write_text(json.dumps({
        "success": True, "commit_sha": "abc1234",
    }), encoding="utf-8")
    return run_dir


def test_replay_coord_run_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        replay_coord_run("does-not-exist", runs_dir=tmp_path / "runs")


def test_replay_coord_run_assembles_report(tmp_path: Path) -> None:
    _seed_run(tmp_path, "20260521T010101-aabb")
    rep = replay_coord_run("20260521T010101-aabb", runs_dir=tmp_path / "runs")
    assert rep.state == "completed"
    assert rep.spec_path == "spec.md"
    assert len(rep.workers) == 1
    assert rep.workers[0]["worker_id"] == "worker-1"
    assert rep.total_events == 2
    assert rep.notify is not None
    assert rep.notify["success"] is True


def test_format_coord_for_human_includes_key_fields(tmp_path: Path) -> None:
    _seed_run(tmp_path, "20260521T010101-aabb")
    rep = replay_coord_run("20260521T010101-aabb", runs_dir=tmp_path / "runs")
    out = format_coord_for_human(rep)
    assert "20260521T010101-aabb" in out
    assert "worker-1" in out
    assert "abc1234" in out


def test_cli_replay_routes_run_id_to_coord(tmp_path: Path) -> None:
    """`harness replay <run_id>` triggers replay_coord_run, not replay_dispatch."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_run(iso_path, "20260521T010101-aabb")
        result = runner.invoke(cli, ["replay", "20260521T010101-aabb"])
    assert result.exit_code == 0, result.output
    assert "20260521T010101-aabb" in result.output
    assert "worker-1" in result.output


def test_cli_replay_still_handles_dispatch_id(tmp_path: Path) -> None:
    """Non-run-id strings still go through the dispatch replay path."""
    from unittest.mock import patch, MagicMock
    runner = CliRunner()
    with patch("harness.replay.replay_dispatch") as mock_rep:
        mock_rep.return_value = MagicMock(
            task_id="disp-1", summary="ok", total_elapsed_ms=42,
            final_outcome="success", events=[],
        )
        result = runner.invoke(cli, ["replay", "disp-1", "--format", "json"])
    assert result.exit_code == 0, result.output
    mock_rep.assert_called_once()
```

## Acceptance

- `python -m pytest tests/test_replay_coord_runs.py` — green.
- Full suite stays green.
- Backwards-compat: `harness replay <dispatch_uuid>` still works the same.

## Constraints

- DO NOT modify `replay_dispatch` or `format_for_human`.
- The CLI command keeps the same name + the same first argument.
- Stdlib only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
