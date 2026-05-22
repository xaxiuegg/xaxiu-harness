"""W5-Path-3: compact per-tick telemetry for ``coord run --watch``.

Reads worker progress jsonl + budget ledger to produce a one-line
status snapshot the operator can scan while a run is in flight.

Pure read-only / never mutates anything.  Best-effort: missing files
return zero values rather than raising.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class WorkerProgress:
    worker_id: str
    completed_steps: int
    total_steps: int
    last_event: str  # "step_start" / "step_done" / "worker_failed" / "?"

    @property
    def fraction(self) -> float:
        return self.completed_steps / self.total_steps if self.total_steps else 0.0


@dataclass(frozen=True)
class RunTelemetry:
    workers: list[WorkerProgress]
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    elapsed_seconds: int
    eta_seconds: int | None  # None when undeterminable


def _read_progress_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return events


def read_worker_progress(
    run_dir: Path,
    plan_tasks: Iterable[dict],
) -> list[WorkerProgress]:
    """For each task in plan, derive (completed_steps, total_steps, last_event).

    Args:
        run_dir: ``runs/<run_id>``
        plan_tasks: iterable of plan task dicts (each with ``worker_id`` and
            ``steps``).  Typically ``plan_obj.model_dump()['tasks']``.

    Returns:
        WorkerProgress per task, in plan order.
    """
    out: list[WorkerProgress] = []
    ckpt_dir = run_dir / "checkpoints"
    for task in plan_tasks:
        wid = str(task.get("worker_id", "?"))
        steps = task.get("steps") or []
        total = len(steps)

        progress_path = ckpt_dir / f"{wid}.progress.jsonl"
        events = _read_progress_jsonl(progress_path)

        completed = sum(1 for e in events if e.get("event") == "step_done")
        last_event = events[-1].get("event", "?") if events else "not_started"

        out.append(WorkerProgress(
            worker_id=wid, completed_steps=completed,
            total_steps=total, last_event=last_event,
        ))
    return out


def read_cost_since(
    ledger_path: Path,
    since_iso: str,
) -> tuple[float, int, int]:
    """Sum ledger cost + tokens for entries with timestamp >= since_iso.

    Returns ``(total_cost_usd, total_in_tokens, total_out_tokens)``.
    """
    if not ledger_path.exists():
        return (0.0, 0, 0)
    total_cost = 0.0
    total_in = 0
    total_out = 0
    try:
        with ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(row.get("timestamp", "")) < since_iso:
                    continue
                total_cost += float(row.get("cost_usd", 0.0))
                total_in += int(row.get("input_tokens", 0))
                total_out += int(row.get("output_tokens", 0))
    except OSError:
        pass
    return (total_cost, total_in, total_out)


def compute_telemetry(
    run_dir: Path,
    plan_tasks: Iterable[dict],
    started_at_iso: str,
    elapsed_seconds: int,
    ledger_path: Path | None = None,
) -> RunTelemetry:
    """Bundle worker progress + cost + ETA for one tick.

    ETA heuristic: average elapsed-seconds-per-completed-step across all
    workers, multiplied by remaining steps.  Returns None when no steps
    have completed yet (cold start).
    """
    workers = read_worker_progress(run_dir, plan_tasks)
    ledger = ledger_path or Path("coord/dev_loop/budget_ledger.jsonl")
    cost, tok_in, tok_out = read_cost_since(ledger, started_at_iso)

    total_done = sum(w.completed_steps for w in workers)
    total_steps = sum(w.total_steps for w in workers)
    remaining = max(0, total_steps - total_done)

    eta: int | None = None
    if total_done > 0 and elapsed_seconds > 0:
        per_step = elapsed_seconds / total_done
        eta = int(per_step * remaining)

    return RunTelemetry(
        workers=workers,
        total_cost_usd=cost,
        total_tokens_in=tok_in,
        total_tokens_out=tok_out,
        elapsed_seconds=elapsed_seconds,
        eta_seconds=eta,
    )


def format_tick_line(tel: RunTelemetry) -> str:
    """Render telemetry as a compact one-liner for terminal display.

    Example:
        "[12s] w1(2/3 step_done) w2(0/2 started)  $0.012  eta=~24s"
    """
    parts: list[str] = [f"[{tel.elapsed_seconds}s]"]
    if tel.workers:
        worker_chunks = []
        for w in tel.workers:
            event_tag = w.last_event.replace("step_", "").replace("worker_", "")
            worker_chunks.append(
                f"{w.worker_id}({w.completed_steps}/{w.total_steps} {event_tag})"
            )
        parts.append(" ".join(worker_chunks))
    if tel.total_cost_usd or tel.total_tokens_in or tel.total_tokens_out:
        parts.append(f"${tel.total_cost_usd:.4f}")
        parts.append(f"tok={tel.total_tokens_in}/{tel.total_tokens_out}")
    if tel.eta_seconds is not None:
        # Pretty-print
        eta = tel.eta_seconds
        if eta < 60:
            eta_str = f"~{eta}s"
        elif eta < 3600:
            eta_str = f"~{eta // 60}m{eta % 60}s"
        else:
            eta_str = f"~{eta // 3600}h{(eta % 3600) // 60}m"
        parts.append(f"eta={eta_str}")
    return "  ".join(parts)
