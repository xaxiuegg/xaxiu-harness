"""W7-AUDIT-POLICY: dispatch MiMo audits for every shipped W7 row in
parallel.

Per operator directive 2026-05-23: every Wn action gets a MiMo audit.
This script retroactively audits all 8 W7 rows that shipped before the
directive landed, then prints a summary table for operator review.

Usage:
    PYTHONPATH=src python -X utf8 scripts/audit_wave7_all.py

Each audit runs ``scripts/audit_task_with_mimo.py <task_id> --commit
<sha>`` in a subprocess so the worker can dispatch in parallel via
ThreadPoolExecutor.  Output is summarised at the end.
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (task_id, commit) — commit anchors the audit to the right diff
TASKS: list[tuple[str, str]] = [
    ("W7-WORKER-BUDGET-HOOK",       "33be9d6"),
    ("W7-MUTATION-WORKER",          "da47f2a"),  # second sweep at gate
    ("W7-KIMI-REASONING-EMPTY",     "da47f2a"),
    ("W7-KIMI-MAX-TOKENS-FLOOR",    "da47f2a"),
    ("W7-MUTATION-ORCH",            "1dae478"),
    ("W7-MUTATION-CONCRETE",        "9ed0e37"),  # second sweep at gate
    ("W7-B1-RETROFIT",              "d074321"),
    ("W7-SPEC-DRIFT",               "8cc50f4"),
    ("W7-CLOSEOUT",                 "8831d18"),
]


def _audit_one(task_id: str, commit: str) -> tuple[str, str, int]:
    """Run one audit; return (task_id, last_line_of_output, exit_code)."""
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [
                sys.executable, "-X", "utf8",
                str(REPO_ROOT / "scripts" / "audit_task_with_mimo.py"),
                task_id, "--commit", commit,
            ],
            cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=180,
            env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
        elapsed = time.monotonic() - started
        # Pick the line containing "confidence=" for the summary
        confidence_line = ""
        for line in proc.stdout.splitlines() + proc.stderr.splitlines():
            if "confidence=" in line:
                confidence_line = line.strip()
        if not confidence_line:
            confidence_line = (proc.stderr or proc.stdout or "")[:200]
        return (task_id, f"{confidence_line}  ({elapsed:.0f}s)",
                proc.returncode)
    except subprocess.TimeoutExpired:
        return (task_id, "TIMEOUT after 180s", 124)
    except Exception as exc:
        return (task_id, f"EXCEPTION: {exc}", 1)


def main() -> int:
    print(f"[audit] dispatching {len(TASKS)} W7 audits in parallel...",
          file=sys.stderr, flush=True)
    started = time.monotonic()
    results: list[tuple[str, str, int]] = []
    with ThreadPoolExecutor(max_workers=len(TASKS)) as pool:
        futures = {pool.submit(_audit_one, t, c): t for t, c in TASKS}
        for f in as_completed(futures):
            results.append(f.result())
            tid, msg, rc = f.result()
            status = "PASS" if rc == 0 else "STOP"
            print(f"  [{status}] {tid:<32} {msg}",
                  file=sys.stderr, flush=True)
    elapsed_s = time.monotonic() - started
    print(f"\n[audit] elapsed {elapsed_s:.0f}s", file=sys.stderr,
          flush=True)

    # Summary table to stdout for downstream parsing / commits
    print("\n## W7 audit roll-up\n")
    print("| Task | Verdict | Confidence | Latency |")
    print("|---|---|---|---|")
    for tid, msg, rc in sorted(results, key=lambda r: r[0]):
        verdict = "PASS" if rc == 0 else "STOP"
        # Parse confidence + latency from the line if present
        conf = "?"
        if "confidence=" in msg:
            import re as _re
            m = _re.search(r"confidence=([0-9.]+)", msg)
            if m:
                conf = m.group(1)
        lat_m = msg.rsplit("(", 1)
        lat = lat_m[-1].rstrip(")") if len(lat_m) > 1 else "?"
        print(f"| {tid} | {verdict} | {conf} | {lat} |")
    return 0 if all(rc == 0 for _, _, rc in results) else 1


if __name__ == "__main__":
    sys.exit(main())
