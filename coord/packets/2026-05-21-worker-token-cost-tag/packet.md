# WORKER-TOKEN-COST-TAG — wire v2 worker dispatches into budget meter

## Goal

`src/harness/coord/worker.py` currently hardcodes `tokens_used: 0` and
never reaches `harness.budget.record_dispatch`, so v2 runs are invisible
to the cost meter and to the new `KILL-CONDITION-WIRING.max_cost_usd`
gate.  This wave fills that gap.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. Extend `EngineResponse` (read-only, already has fields)

Check `src/harness/engines/base.py` — if EngineResponse lacks
`tokens_in: int = 0` / `tokens_out: int = 0` / `cost_usd: float = 0.0`
fields, ADD them.  All three default to 0 / 0.0 so existing callers stay
compatible.  Skip this step if the fields already exist.

### 2. Update `src/harness/coord/worker.py::run_worker`

Find this block (around line 240):

```python
    result: dict[str, Any] = {
        "schema_version": 1,
        "worker_id": task_obj.worker_id,
        "run_id": run_dir.name,
        "state": final_state,
        "started_at": started_at,
        "finished_at": now_iso(),
        "steps_completed": steps_completed,
        "files_modified": files_modified,
        "test_summary": tests,
        "commit_sha": commit_sha,
        "error_tag": None if final_state == "completed" else "L3.worker.E_TEST_FAILED",
        "diagnostic": "",
        "tokens_used": 0,
```

Replace `"tokens_used": 0,` with logic that aggregates across dispatch
calls inside the step loop.  Strategy:

a) At the top of `run_worker`, after the `files_modified` initialization,
   add:
   ```python
   total_tokens: int = 0
   total_cost_usd: float = 0.0
   ```

b) Inside the step-edit branch where `result = dispatch_packet(...)` lands
   (search for `dispatch_packet(` inside the run_worker function),
   immediately after the `if result.success and result.text.strip():`
   block, add:
   ```python
   # Accumulate token + cost telemetry for budget meter
   total_tokens += int(getattr(result, "tokens_used", 0) or 0)
   total_cost_usd += float(getattr(result, "cost_usd", 0.0) or 0.0)
   ```

c) Replace `"tokens_used": 0,` with `"tokens_used": total_tokens,`
   and ADD a new key `"cost_usd": total_cost_usd,` immediately after it.

### 3. Record into budget ledger

After the `write_checkpoint(checkpoint_path, ckpt)` at the END of
run_worker (right before the `result = {...}` dict), add a best-effort
budget recording block:

```python
    # Record into per-engine budget ledger (best-effort, no fail-loud)
    try:
        from harness.budget import record_dispatch as _budget_record
        _budget_record(
            engine=engine,
            tokens_in=0,  # split not currently tracked at worker level
            tokens_out=total_tokens,
            cost_usd=total_cost_usd,
            run_id=run_dir.name,
            worker_id=task_obj.worker_id,
        )
    except Exception:
        pass  # ledger best-effort — never fail a worker for budget I/O
```

If `harness.budget.record_dispatch` has a different signature, fall back
to whatever the existing signature is — search the budget module to
confirm before patching.  Skip the call if the function doesn't exist.

### 4. WorkerResult schema bump

In `src/harness/coord/schemas.py`, find `class WorkerResult` and add a
new optional field:

```python
cost_usd: float = Field(ge=0.0, default=0.0)
```

Place it right after the existing `tokens_used` field.  Keep
`extra="forbid"`.

### 5. Tests

New file `tests/test_worker_token_cost.py`:

```python
"""Tests for WORKER-TOKEN-COST-TAG: worker accumulates token + cost telemetry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.coord.schemas import WorkerStep, WorkerTask


def _mk_task(target_files: list[str]) -> dict:
    return WorkerTask(
        worker_id="worker-1",
        title="t",
        description="d",
        steps=[WorkerStep(
            step_id="s1", kind="edit", instruction="x",
            target_files=target_files, expected_diff_lines=1,
        )],
    ).model_dump()


def test_run_worker_accumulates_tokens_from_dispatch(tmp_path: Path, monkeypatch) -> None:
    """worker.run_worker pulls tokens_used / cost_usd off EngineResponse."""
    from harness.coord import worker as worker_module

    # Stub dispatch_packet to return a fake DispatchResult with telemetry
    fake_result = MagicMock(
        success=True,
        text="FILE: x.txt\n<<<<<<< SEARCH\n=======\nhello\n>>>>>>> REPLACE\n",
        tokens_used=123,
        cost_usd=0.45,
    )
    monkeypatch.setattr(worker_module, "dispatch_packet", lambda **kw: fake_result)

    # Stub git operations (worker tries to commit)
    monkeypatch.setattr(worker_module, "_git_commit", lambda *a, **kw: "deadbee")

    # Stub pytest
    monkeypatch.setattr(worker_module, "_run_pytest", lambda *a, **kw: {
        "ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0,
    })

    # Stub worktree to use a real tmp dir
    monkeypatch.setattr(worker_module, "worktree_path", lambda *a, **kw: tmp_path / "wt")
    (tmp_path / "wt").mkdir()

    run_dir = tmp_path / "runs" / "test-run"
    run_dir.mkdir(parents=True)

    result = worker_module.run_worker(
        _mk_task(["x.txt"]), run_dir, engine="mock", project_root=tmp_path,
    )

    assert result["tokens_used"] == 123
    assert result["cost_usd"] == pytest.approx(0.45)


def test_run_worker_handles_missing_telemetry_gracefully(tmp_path: Path, monkeypatch) -> None:
    """Old-shape EngineResponse (no tokens_used / cost_usd) doesn't crash."""
    from harness.coord import worker as worker_module

    fake_result = MagicMock(
        success=True,
        text="FILE: x.txt\n<<<<<<< SEARCH\n=======\nhi\n>>>>>>> REPLACE\n",
        spec=["success", "text"],  # no tokens_used / cost_usd attrs
    )
    monkeypatch.setattr(worker_module, "dispatch_packet", lambda **kw: fake_result)
    monkeypatch.setattr(worker_module, "_git_commit", lambda *a, **kw: "deadbee")
    monkeypatch.setattr(worker_module, "_run_pytest", lambda *a, **kw: {
        "ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0,
    })
    monkeypatch.setattr(worker_module, "worktree_path", lambda *a, **kw: tmp_path / "wt")
    (tmp_path / "wt").mkdir()

    run_dir = tmp_path / "runs" / "test-run-2"
    run_dir.mkdir(parents=True)

    result = worker_module.run_worker(
        _mk_task(["x.txt"]), run_dir, engine="mock", project_root=tmp_path,
    )
    assert result["tokens_used"] == 0
    assert result["cost_usd"] == 0.0
```

## Acceptance

- `python -m pytest tests/test_worker_token_cost.py` — all green.
- `python -m pytest --tb=short -q` — overall suite stays green.
- Manual: a v2 mock run produces a WorkerResult with `cost_usd >= 0.0`
  and the budget ledger gains an entry.

## Constraints

- DO NOT modify any other test files.
- DO NOT change the existing dispatch_packet signature.
- Keep budget.record_dispatch wiring inside a try/except.
- Backwards-compat: existing EngineResponse instances without the new
  fields must still flow through `run_worker` without raising
  (use `getattr(..., default)`).

## Engine guidance

This is a single-file surgical change to worker.py + schemas.py + 1 new
test.  swarm/kimi or swarm/kimi-api both work.  Timeout 420s.
