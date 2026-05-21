# SWARM-LANDING-VERIFY — `harness swarm verify-landings`

## Goal

Per `feedback_kimi_cli_incremental_edits` in operator memory: Kimi-CLI
applies Edit/Write tool calls incrementally, and a swarm "timeout" tag
can coexist with files that HAVE been written.  Operators currently have
no scriptable way to falsify "timeout=failed".

Add a verb that takes a list of files-or-paths the operator expected
to be edited, looks at recent git diff + xaxiu-swarm audit output, and
reports which expected paths actually got mutated.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/swarm_verify.py`

```python
"""Verify Kimi-CLI landings against expected file paths (SWARM-LANDING-VERIFY).

Closes the "timeout-but-actually-landed" gap documented in
``feedback_kimi_cli_incremental_edits``.  Reads the most recent
``.swarm/runs/<id>/swarm.json`` (or one specified via --run-id), pairs
each completed worker against its declared deliverable + the actual
git diff, and reports which expected paths the worker mutated.

Output is a list of LandingResult per expected path:

  expected_path, status (mutated | unmutated | not_in_diff), worker_id,
  swarm_status (completed | timeout | failed | running)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_DEFAULT_SWARM_ROOT = Path(".swarm") / "runs"


@dataclass(frozen=True)
class LandingResult:
    expected_path: str
    status: str          # "mutated" | "unmutated" | "not_in_diff"
    worker_id: str | None = None
    swarm_status: str | None = None


def _latest_swarm_run(swarm_root: Path = _DEFAULT_SWARM_ROOT) -> Path | None:
    if not swarm_root.exists():
        return None
    runs = sorted(p for p in swarm_root.iterdir() if p.is_dir())
    return runs[-1] if runs else None


def _read_swarm_state(run_dir: Path) -> dict | None:
    sj = run_dir / "swarm.json"
    if not sj.exists():
        return None
    try:
        return json.loads(sj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _git_diff_files(scope: str = "HEAD") -> set[str]:
    """Return paths changed in *scope*.  Empty set on git failure."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", scope],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return set()
        return {p.strip() for p in proc.stdout.splitlines() if p.strip()}
    except Exception:
        return set()


def _untracked_files() -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return set()
        return {p.strip() for p in proc.stdout.splitlines() if p.strip()}
    except Exception:
        return set()


def verify_landings(
    expected_paths: Iterable[str],
    *,
    run_id: str | None = None,
    swarm_root: Path = _DEFAULT_SWARM_ROOT,
    git_scope: str = "HEAD",
) -> list[LandingResult]:
    """Cross-reference expected paths with git mutations + swarm worker state."""
    expected = list(expected_paths)
    if not expected:
        return []

    # Find the swarm run
    if run_id:
        run_dir = swarm_root / run_id
    else:
        run_dir = _latest_swarm_run(swarm_root)

    workers: list[dict] = []
    if run_dir and run_dir.exists():
        state = _read_swarm_state(run_dir) or {}
        workers = state.get("workers") or []

    modified = _git_diff_files(git_scope) | _untracked_files()

    results: list[LandingResult] = []
    for exp in expected:
        norm = exp.replace("\\", "/")
        status = "mutated" if norm in modified else "unmutated"
        # Best-effort: pair with a worker whose packet path mentions exp
        wid: str | None = None
        wstatus: str | None = None
        for w in workers:
            packet = (w.get("packet") or "").replace("\\", "/")
            if norm in packet:
                wid = w.get("id")
                wstatus = w.get("status")
                break
        if status == "unmutated" and modified and norm not in modified:
            status = "not_in_diff"
        results.append(LandingResult(
            expected_path=exp, status=status, worker_id=wid, swarm_status=wstatus,
        ))
    return results


def summarize(results: list[LandingResult]) -> dict[str, int]:
    summary = {"mutated": 0, "unmutated": 0, "not_in_diff": 0}
    for r in results:
        if r.status in summary:
            summary[r.status] += 1
        else:
            summary["unmutated"] += 1
    return summary
```

### 2. New CLI verb — TOP LEVEL

In `src/harness/cli.py`, find another top-level command (e.g.
`@cli.command(name="doctor")` or `@cli.command(name="panic-dump")`).
Add a NEW top-level command:

```python
@cli.command(name="swarm-verify")
@click.option("--expect-edits-in", "expect_paths", multiple=True, required=True,
              help="Path(s) expected to be mutated by the last swarm.")
@click.option("--run-id", default=None,
              help="Swarm run_id (defaults to latest under .swarm/runs/).")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty")
def swarm_verify_cmd(expect_paths: tuple[str, ...], run_id: str | None, fmt: str) -> None:
    """Verify the last (or named) swarm actually wrote the expected paths.

    Exits 0 only when EVERY expected path has status='mutated'.  Closes
    the 'Kimi timeout coexists with landed edits' gap.
    """
    import dataclasses
    from harness.swarm_verify import verify_landings, summarize

    results = verify_landings(list(expect_paths), run_id=run_id)
    summary = summarize(results)
    all_landed = summary["mutated"] == len(results) and summary["unmutated"] == 0 and summary["not_in_diff"] == 0

    if fmt == "json":
        click.echo(json.dumps({
            "all_landed": all_landed,
            "summary": summary,
            "results": [dataclasses.asdict(r) for r in results],
        }, indent=2))
    else:
        click.echo(f"summary: {summary}  (all_landed={all_landed})")
        for r in results:
            click.echo(
                f"  {r.status:<14} {r.expected_path}  "
                f"worker={r.worker_id or '-'} swarm_status={r.swarm_status or '-'}"
            )
    sys.exit(0 if all_landed else 1)
```

### 3. Tests

`tests/test_swarm_verify.py`:

```python
"""Tests for SWARM-LANDING-VERIFY."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.swarm_verify import (
    LandingResult, summarize, verify_landings, _latest_swarm_run,
)


def test_latest_swarm_run_returns_none_when_root_missing(tmp_path: Path) -> None:
    assert _latest_swarm_run(tmp_path / "nope") is None


def test_latest_swarm_run_returns_newest(tmp_path: Path) -> None:
    (tmp_path / "20260520T000000-aaaa").mkdir(parents=True)
    (tmp_path / "20260521T000000-bbbb").mkdir(parents=True)
    out = _latest_swarm_run(tmp_path)
    assert out.name == "20260521T000000-bbbb"


def test_verify_landings_empty_expected_returns_empty() -> None:
    assert verify_landings([]) == []


def test_verify_landings_reports_mutated(tmp_path: Path) -> None:
    """When git diff includes the expected path, status=mutated."""
    with patch("harness.swarm_verify._git_diff_files", return_value={"src/x.py"}), \
         patch("harness.swarm_verify._untracked_files", return_value=set()), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        results = verify_landings(["src/x.py"])
    assert len(results) == 1
    assert results[0].status == "mutated"


def test_verify_landings_reports_unmutated(tmp_path: Path) -> None:
    with patch("harness.swarm_verify._git_diff_files", return_value=set()), \
         patch("harness.swarm_verify._untracked_files", return_value=set()), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        results = verify_landings(["src/y.py"])
    assert results[0].status == "unmutated"


def test_verify_landings_includes_untracked_as_mutated(tmp_path: Path) -> None:
    """A new file shows up in untracked, not git-diff."""
    with patch("harness.swarm_verify._git_diff_files", return_value=set()), \
         patch("harness.swarm_verify._untracked_files", return_value={"src/new.py"}), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        results = verify_landings(["src/new.py"])
    assert results[0].status == "mutated"


def test_summarize_counts_each_bucket() -> None:
    rs = [
        LandingResult("a", "mutated"),
        LandingResult("b", "mutated"),
        LandingResult("c", "unmutated"),
    ]
    s = summarize(rs)
    assert s["mutated"] == 2
    assert s["unmutated"] == 1


def test_cli_swarm_verify_all_landed(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    with patch("harness.swarm_verify._git_diff_files", return_value={"src/x.py"}), \
         patch("harness.swarm_verify._untracked_files", return_value=set()), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        result = runner.invoke(cli, [
            "swarm-verify", "--expect-edits-in", "src/x.py",
        ])
    assert result.exit_code == 0
    assert "all_landed=True" in result.output


def test_cli_swarm_verify_missing_path_exits_1(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    with patch("harness.swarm_verify._git_diff_files", return_value=set()), \
         patch("harness.swarm_verify._untracked_files", return_value=set()), \
         patch("harness.swarm_verify._latest_swarm_run", return_value=None):
        result = runner.invoke(cli, [
            "swarm-verify", "--expect-edits-in", "src/missing.py",
        ])
    assert result.exit_code == 1
```

## Acceptance

- `python -m pytest tests/test_swarm_verify.py` — green.
- Full suite stays green.
- `harness swarm-verify --expect-edits-in src/foo.py` returns 0 or 1.

## Constraints

- DO NOT modify `xaxiu-swarm` (external tool).
- Stdlib + subprocess only.
- Keep swarm_verify.py under 150 LOC.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
