# SPEC-FROM-NL-VERB — `harness coord plan-from-description "<NL>"`

## Goal

`harness coord plan --spec spec.md` requires the operator to author a
markdown spec file first.  For quick non-technical onboarding the
operator should be able to type:

    harness coord plan-from-description "Add a /health endpoint to dashboard with JSON {status: ok}"

and get a WavePlan generated from the natural-language description.

Mirrors `harness adapter from-description` (already shipped W5/B).

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/coord/planner.py`

Add a sibling to the existing `plan()` function (DO NOT modify plan()):

```python
def plan_from_description(
    description: str,
    *,
    run_id: str | None = None,
    engine: str = "claude",
    model: str | None = None,
    project_root: Path | None = None,
    max_retries: int = 1,
) -> WavePlan:
    """Decompose a natural-language description into a WavePlan.

    Writes the description to a temp .md file and delegates to plan().
    Keeps wrapper logic small so callers (the new CLI verb) stay tiny.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(f"# Task (from natural language)\n\n{description}\n")
        tmp_path = Path(tmp.name)
    try:
        return plan(
            tmp_path,
            run_id=run_id,
            engine=engine,
            model=model,
            project_root=project_root,
            max_retries=max_retries,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
```

### 2. New CLI subcommand

Find `@coord_group.command(name="plan")` in `src/harness/cli.py` (around
line 1255) and add a NEW command IMMEDIATELY AFTER it (not modifying
coord_plan):

```python
@coord_group.command(name="plan-from-description")
@click.argument("description")
@click.option("--engine", default="claude",
              help="Planner engine: claude | kimi | kimi-api | deepseek | mock.")
@click.option("--run-id", default=None)
def coord_plan_from_description(description: str, engine: str, run_id: str | None) -> None:
    """Generate a plan.json from a one-line natural-language description."""
    from harness.coord.planner import plan_from_description, write_plan
    waveplan = plan_from_description(description, engine=engine, run_id=run_id)
    run_dir = Path("runs") / waveplan.run_id
    out = write_plan(waveplan, run_dir)
    click.echo(f"plan.json written to {out} (run_id={waveplan.run_id})")
    click.echo(f"  {len(waveplan.tasks)} task(s); planner_engine={waveplan.planner_engine}")
```

### 3. Tests

`tests/test_coord_plan_from_description.py`:

```python
"""Tests for `harness coord plan-from-description`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.planner import plan_from_description
from harness.coord.schemas import WavePlan, WorkerTask, WorkerStep


def _stub_waveplan(run_id: str = "20260521T000000-aabb") -> WavePlan:
    return WavePlan(
        run_id=run_id, spec_path="x", created_at="2026-05-21T00:00:00+00:00",
        planner_engine="mock",
        tasks=[WorkerTask(
            worker_id="worker-1", title="t", description="d",
            steps=[WorkerStep(step_id="s1", kind="edit", instruction="x",
                              target_files=["x.txt"], expected_diff_lines=1)],
        )],
    )


def test_plan_from_description_delegates_to_plan(monkeypatch) -> None:
    """plan_from_description writes description to temp file and calls plan()."""
    captured: dict = {}

    def fake_plan(path, **kwargs):
        captured["path"] = path
        captured["body"] = Path(path).read_text(encoding="utf-8")
        captured["kwargs"] = kwargs
        return _stub_waveplan()

    monkeypatch.setattr("harness.coord.planner.plan", fake_plan)
    waveplan = plan_from_description("Add /health endpoint", engine="mock")
    assert waveplan.run_id == "20260521T000000-aabb"
    assert "Add /health endpoint" in captured["body"]
    # Temp file was deleted after call
    assert not Path(captured["path"]).exists()


def test_cli_plan_from_description_writes_plan_json(monkeypatch, tmp_path: Path) -> None:
    """`harness coord plan-from-description` writes runs/<id>/plan.json."""
    runner = CliRunner()
    with patch("harness.coord.planner.plan_from_description") as mock_p, \
         patch("harness.coord.planner.write_plan") as mock_w:
        mock_p.return_value = _stub_waveplan()
        mock_w.return_value = tmp_path / "runs" / "20260521T000000-aabb" / "plan.json"
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, [
                "coord", "plan-from-description", "Add a /health endpoint",
                "--engine", "mock",
            ])
    assert result.exit_code == 0, result.output
    assert "plan.json written" in result.output
    assert "1 task(s)" in result.output


def test_cli_plan_from_description_propagates_run_id(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    with patch("harness.coord.planner.plan_from_description") as mock_p, \
         patch("harness.coord.planner.write_plan") as mock_w:
        mock_p.return_value = _stub_waveplan(run_id="20260521T010101-cccc")
        mock_w.return_value = tmp_path / "runs" / "20260521T010101-cccc" / "plan.json"
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, [
                "coord", "plan-from-description", "Test",
                "--engine", "mock", "--run-id", "20260521T010101-cccc",
            ])
    assert result.exit_code == 0, result.output
    # run_id forwarded to plan_from_description
    assert mock_p.call_args.kwargs.get("run_id") == "20260521T010101-cccc"
```

## Acceptance

- `python -m pytest tests/test_coord_plan_from_description.py` — green.
- Full suite stays green.
- `harness coord plan-from-description --help` shows the new verb.

## Constraints

- DO NOT modify the existing `plan()` function.
- DO NOT touch `coord_plan` CLI command.
- Stdlib only (tempfile).
- New planner helper under 30 LOC; new CLI verb under 20 LOC.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
