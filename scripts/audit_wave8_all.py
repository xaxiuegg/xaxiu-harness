"""W8 batch audit: all W8 rows + the 4 W7 STOPs (re-audited with the
W8-AUDIT-PROMPT limits raised) in parallel.

Pattern mirrors audit_wave7_all.py.  Per W7-AUDIT-POLICY directive +
W8-AUDIT-PROMPT fix.
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (task_id, commit) — commit anchors each audit
TASKS: list[tuple[str, str]] = [
    # The 4 W7 STOPs — re-audit with the new W8-AUDIT-PROMPT limits
    ("W7-CLOSEOUT",                "8831d18"),
    ("W7-MUTATION-ORCH",           "1dae478"),
    ("W7-KIMI-MAX-TOKENS-FLOOR",   "da47f2a"),
    ("W7-SPEC-DRIFT",              "8cc50f4"),
    # New W8 rows.  W8-PLAN is a meta-row for the plan doc itself, not
    # a code task — exclude from audit sweep (no acceptance criteria).
    # W8-AUDIT-PROMPT spans two commits: 9aea866 (script change) +
    # 083a1bf (re-audit evidence).  Anchor at the re-audit commit so the
    # auditor sees the full multi-step deliverable.
    ("W8-STOP-HOOK",               "9aea866"),
    ("W8-AUDIT-PROMPT",            "083a1bf"),
    ("W8-PREFLIGHT-FIX",           "3dc8593"),
    ("W8-OPERATOR-RUNBOOK",        "6fbece0"),
    ("W8-STATUS-HUMAN",            "6fbece0"),
    ("W8-ENGINES-HEAL",            "6fbece0"),
]


def _audit_one(task_id: str, commit: str) -> tuple[str, str, int]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [
                sys.executable, "-X", "utf8",
                str(REPO_ROOT / "scripts" / "audit_task_with_mimo.py"),
                task_id, "--commit", commit,
            ],
            cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=240,
            env={**__import__("os").environ,
                 "PYTHONPATH": str(REPO_ROOT / "src")},
        )
        elapsed = time.monotonic() - started
        conf_line = ""
        for line in (proc.stdout + proc.stderr).splitlines():
            if "confidence=" in line:
                conf_line = line.strip()
        if not conf_line:
            conf_line = (proc.stderr or proc.stdout or "")[:200]
        return (task_id, f"{conf_line}  ({elapsed:.0f}s)",
                proc.returncode)
    except subprocess.TimeoutExpired:
        return (task_id, "TIMEOUT after 240s", 124)
    except Exception as exc:
        return (task_id, f"EXCEPTION: {exc}", 1)


def main() -> int:
    print(f"[audit] dispatching {len(TASKS)} audits in parallel...",
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

    print("\n## W8 audit roll-up\n")
    print("| Task | Verdict | Confidence | Latency |")
    print("|---|---|---|---|")
    for tid, msg, rc in sorted(results, key=lambda r: r[0]):
        verdict = "PASS" if rc == 0 else "STOP"
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
