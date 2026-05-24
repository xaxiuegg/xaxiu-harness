"""W11-AUDIT-ALL-W10-ROWS — backfill avg-of-3 audits on every W10 commit.

W10 closeout flagged audit deficit: only W10-PREFLIGHT-EXIT-CODE-SEMANTICS
got a formal --avg-of-N=3 audit before the W10-MIMO-FILTER-INVESTIGATION
swap.  Now that DeepSeek is primary (~30s vs ~180s+ pre-swap), backfill
audits for every W10 row at its commit SHA.

Pattern mirrors scripts/audit_wave8_all.py and audit_wave7_all.py.
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (task_id, commit) — each row's primary commit
TASKS: list[tuple[str, str]] = [
    ("W10-PREFLIGHT-EXIT-CODE-SEMANTICS", "0e9535d"),
    ("W10-DAILY-QUICKSTART-VERB",         "c44e855"),
    ("W10-PREFLIGHT-REMEDIATION-CARDS",   "0871e80"),
    ("W10-PROFILE-AWARE-DEFAULTS",        "0871e80"),
    ("W10-STATUS-CSV-OVERWHELM",          "0871e80"),
    ("W10-ENV-VAR-WIZARD",                "7698602"),
    ("W10-DPAPI-SEEDING-VISIBILITY",      "7698602"),
    ("W10-MIMO-FILTER-INVESTIGATION",     "b3476c2"),
    ("W10-AUDIT-FOLLOWUP-COMMIT-POLICY",  "b3476c2"),
    ("W10-FRESH-CANARY-MODULES",          "b3476c2"),
]


def _audit_one(task_id: str, commit: str) -> tuple[str, str, int]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [
                sys.executable, "-X", "utf8",
                str(REPO_ROOT / "scripts" / "audit_task_with_mimo.py"),
                task_id, "--commit", commit, "--avg-of-N", "3",
            ],
            cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=420,
            env={**__import__("os").environ,
                 "PYTHONPATH": str(REPO_ROOT / "src")},
        )
        elapsed = time.monotonic() - started
        info_line = ""
        for line in (proc.stdout + proc.stderr).splitlines():
            if "mean=" in line or "confidence=" in line:
                info_line = line.strip()
        if not info_line:
            info_line = (proc.stderr or proc.stdout or "")[:200]
        return (task_id, f"{info_line}  ({elapsed:.0f}s)",
                proc.returncode)
    except subprocess.TimeoutExpired:
        return (task_id, "TIMEOUT after 420s", 124)
    except Exception as exc:
        return (task_id, f"EXCEPTION: {exc}", 1)


def main() -> int:
    print(f"[audit] dispatching {len(TASKS)} avg-of-3 audits in parallel "
          f"(post-MiMo-filter-swap; DeepSeek primary)...",
          file=sys.stderr, flush=True)
    started = time.monotonic()
    results: list[tuple[str, str, int]] = []
    # Cap concurrency at 5 to stay polite with DeepSeek rate limits
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_audit_one, t, c): t for t, c in TASKS}
        for f in as_completed(futures):
            results.append(f.result())
            tid, msg, rc = f.result()
            status = "PASS" if rc == 0 else "STOP"
            print(f"  [{status}] {tid:<38} {msg}",
                  file=sys.stderr, flush=True)
    elapsed_s = time.monotonic() - started
    print(f"\n[audit] elapsed {elapsed_s:.0f}s", file=sys.stderr,
          flush=True)

    print("\n## W10 audit backfill roll-up (W11-AUDIT-ALL-W10-ROWS)\n")
    print("| Task | Verdict | Mean | Stdev | Pass-Count | Latency |")
    print("|---|---|---|---|---|---|")
    import re as _re
    for tid, msg, rc in sorted(results, key=lambda r: r[0]):
        verdict = "PASS" if rc == 0 else "STOP"
        mean_m = _re.search(r"mean=([0-9.]+)", msg)
        stdev_m = _re.search(r"stdev=([0-9.]+)", msg)
        pass_m = _re.search(r"pass=(\d+/\d+)", msg)
        lat_m = msg.rsplit("(", 1)
        mean = mean_m.group(1) if mean_m else "?"
        stdev = stdev_m.group(1) if stdev_m else "?"
        pass_count = pass_m.group(1) if pass_m else "?"
        lat = lat_m[-1].rstrip(")") if len(lat_m) > 1 else "?"
        print(f"| {tid} | {verdict} | {mean} | {stdev} | {pass_count} | {lat} |")
    return 0 if all(rc == 0 for _, _, rc in results) else 1


if __name__ == "__main__":
    sys.exit(main())
