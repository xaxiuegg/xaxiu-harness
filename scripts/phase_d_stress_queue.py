"""Phase D stress test — multi-spec sequential queue.

Drives 5-6 pilot specs through `coord run --watch --no-merge` back-to-
back, mixing engines (MiMo, DeepSeek+fallback, Kimi+fallback) to
simulate a real unattended overnight workload at smaller scale.

Tracks: wall time per pilot, success/failure, engine_used per worker,
and aggregate cost from the W4-K-tracked budget ledger.  Writes a
final synthesis to coord/coverage/phase_d_stress_<stamp>.json.

Run from project root:
    PYTHONPATH=src python scripts/phase_d_stress_queue.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

QUEUE = [
    # (spec_path, engine, fallback_engine_or_None, label)
    ("spec/samples/pilot-G1-script-docstring.md",       "swarm/mimo",     None,            "G1-mimo"),
    ("spec/samples/pilot-G1-script-docstring.md",       "swarm/deepseek", "swarm/mimo",    "G1-deepseek+mimo"),
    ("spec/samples/pilot-G1-script-docstring.md",       "swarm/kimi",     "swarm/mimo",    "G1-kimi+mimo"),
    ("spec/samples/pilot-G3-multiworker-independent.md", "swarm/mimo",     "swarm/deepseek","G3-mimo+ds"),
    ("spec/samples/pilot-readme-pilot-note.md",         "swarm/mimo",     None,            "readme-mimo"),
]


def _ledger_total() -> tuple[float, int, int]:
    """Read budget ledger and sum cost + tokens since start."""
    ledger = Path("coord/dev_loop/budget_ledger.jsonl")
    if not ledger.exists():
        return (0.0, 0, 0)
    cost = 0.0
    tin = 0
    tout = 0
    with ledger.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            cost += float(r.get("cost_usd", 0))
            tin += int(r.get("input_tokens", 0))
            tout += int(r.get("output_tokens", 0))
    return (cost, tin, tout)


def _run_one(spec: str, engine: str, fallback: str | None, label: str) -> dict:
    """Plan + run one pilot.  Return result dict."""
    print(f"\n{'='*60}\n[{label}] starting: {spec} engine={engine} fallback={fallback}\n{'='*60}", flush=True)

    # Plan
    plan_started = time.monotonic()
    plan = subprocess.run(
        [sys.executable, "-m", "harness", "coord", "plan",
         "--spec", spec, "--engine", "claude"],
        capture_output=True, text=True, timeout=120,
        env={**__import__("os").environ, "PYTHONPATH": "src"},
    )
    if plan.returncode != 0:
        print(f"  PLAN FAILED: {plan.stderr[:300]}", flush=True)
        return {"label": label, "spec": spec, "engine": engine,
                "fallback": fallback, "outcome": "plan_failed",
                "stderr": plan.stderr[:500]}

    # Extract run-id from "plan: runs\<run-id>\plan.json"
    rid = None
    for line in plan.stdout.splitlines():
        if "plan:" in line and "runs" in line:
            parts = line.split("runs")[-1]
            # strip leading separator and "\plan.json"
            rid_part = parts.lstrip("\\/").split("\\")[0].split("/")[0]
            rid = rid_part
            break
    if not rid:
        return {"label": label, "spec": spec, "engine": engine,
                "fallback": fallback, "outcome": "no_run_id",
                "stdout": plan.stdout[:300]}
    print(f"  rid={rid}", flush=True)

    # Run
    cmd = [
        sys.executable, "-m", "harness", "coord", "run",
        "--spec", spec, "--run-id", rid, "--engine", engine,
        "--proxy", "off", "--watch", "--watch-interval", "5",
        "--watch-max-seconds", "600", "--no-merge",
    ]
    if fallback:
        cmd.extend(["--fallback-engine", fallback])

    run_started = time.monotonic()
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=900,
        env={**__import__("os").environ, "PYTHONPATH": "src"},
    )
    elapsed = int(time.monotonic() - run_started)

    # Inspect checkpoints
    run_dir = Path("runs") / rid
    ckpt_dir = run_dir / "checkpoints"
    workers: list[dict] = []
    if ckpt_dir.exists():
        for ckpt_path in sorted(ckpt_dir.glob("worker-*.json")):
            try:
                ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
                workers.append({
                    "worker_id": ckpt.get("worker_id"),
                    "state": ckpt.get("state"),
                    "files_modified": ckpt.get("files_modified") or [],
                    "commit_sha": ckpt.get("commit_sha"),
                })
            except Exception:
                pass

    # Read engine_used from progress jsonl
    engine_used = []
    if ckpt_dir.exists():
        for prog in sorted(ckpt_dir.glob("worker-*.progress.jsonl")):
            try:
                for line in prog.read_text(encoding="utf-8").splitlines():
                    ev = json.loads(line)
                    if ev.get("event") == "step_engine_used":
                        engine_used.append({"step": ev.get("step_id"),
                                            "engine": ev.get("engine_used")})
            except Exception:
                pass

    all_completed = workers and all(w["state"] == "completed" for w in workers)
    return {
        "label": label, "spec": spec, "rid": rid,
        "engine": engine, "fallback": fallback,
        "elapsed_s": elapsed, "outcome": "completed" if all_completed else "failed",
        "workers": workers, "engine_used": engine_used,
        "run_exit": proc.returncode,
    }


def main() -> int:
    print(f"=== Phase D stress queue: {len(QUEUE)} pilots ===", flush=True)
    started_at = datetime.now(timezone.utc).isoformat()
    cost_start, tin_start, tout_start = _ledger_total()
    print(f"baseline cost=${cost_start:.4f} tokens_in={tin_start} tokens_out={tout_start}", flush=True)

    results: list[dict] = []
    queue_start = time.monotonic()
    for spec, engine, fallback, label in QUEUE:
        r = _run_one(spec, engine, fallback, label)
        results.append(r)
        print(f"  -> {r['outcome']} in {r.get('elapsed_s', '?')}s", flush=True)

    queue_elapsed = int(time.monotonic() - queue_start)
    cost_end, tin_end, tout_end = _ledger_total()

    # Summary
    successes = sum(1 for r in results if r["outcome"] == "completed")
    print(f"\n=== SUMMARY ===", flush=True)
    print(f"queue elapsed: {queue_elapsed}s", flush=True)
    print(f"pilots: {successes}/{len(results)} completed", flush=True)
    print(f"delta cost: ${cost_end - cost_start:.4f}", flush=True)
    print(f"delta tokens: in={tin_end - tin_start} out={tout_end - tout_start}", flush=True)

    report_path = Path("coord/coverage") / (
        "phase_d_stress_" +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
        ".json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "started_at": started_at,
        "queue_elapsed_s": queue_elapsed,
        "pilots": results,
        "cost_delta_usd": cost_end - cost_start,
        "tokens_in_delta": tin_end - tin_start,
        "tokens_out_delta": tout_end - tout_start,
    }, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}", flush=True)
    return 0 if successes == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
