"""Retroactive 20-agent panel sweep across all shipped W11 rows.

Per operator directive 2026-05-25: every W-action needs a 20-persona
panel audit, retroactive + active.  This script handles the
retroactive sweep — fire the panel against each W11 commit
sequentially (one row's panel at a time; 10-thread internal
parallelism per panel).

Sequencing rationale: 20 personas × 12 rows = 240 concurrent
dispatches if fully parallel — that floods both engines.  Better
to serialize the rows + parallelize within each (10 workers max).

Output: one panel report per row at
coord/reviews/w-action-audits/<stamp>_<task-id>_panel20.md
+ a master roll-up at coord/reviews/w-action-audits/w11-rollup.md.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_w_action_panel20 import _format_report, run_panel  # noqa: E402


# (task_id, commit) for every shipped W11 row.  Pulled from
# git log + STATUS.csv inspection.
W11_TASKS: list[tuple[str, str]] = [
    # Pre-flight
    ("W11-AUDIT-ALL-W10-ROWS",              "35bece7"),
    ("W11-ADAPTER-VALIDATE-JSON",           "35bece7"),
    ("W11-HIDE-ADVANCED-VERBS",             "20c9840"),
    ("W11-MUTATION-PATTERN-EXPANSION",      "20c9840"),
    # Wave 11-A
    ("W11-AGENT-INIT-VERB",                 "HEAD~6"),  # resolve via git log
    ("W11-DPAPI-CROSS-PLATFORM",            "HEAD~5"),
    # Wave 11-A.5
    ("W11-PYTHON-SDK-API-STUBS",            "91d277f"),
    # Wave 11-B
    ("W11-CONTEXT-FRUGAL-RETURN-SCHEMA",    "a8c3489"),
    ("W11-DISPATCH-CACHE",                  "HEAD~3"),
    ("W11-CONTEXT-FRUGAL-RETURN-LAZY",      "ceb1c10"),
    ("W11-RETRIEVE-API",                    "HEAD"),
]


OUT_DIR = REPO_ROOT / "coord" / "reviews" / "w-action-audits"
ROLLUP_PATH = OUT_DIR / "w11-rollup.md"


def _resolve_sha(commit: str) -> str:
    """Resolve HEAD~N references to actual SHAs."""
    if commit.startswith("HEAD"):
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--short=12", commit],
                cwd=REPO_ROOT, capture_output=True, text=True, check=True,
            )
            return out.stdout.strip() or commit
        except subprocess.CalledProcessError:
            return commit
    return commit


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rollup_rows: list[tuple[str, str, dict]] = []

    started = time.monotonic()
    for task_id, commit_spec in W11_TASKS:
        commit = _resolve_sha(commit_spec)
        print(f"\n[w11-sweep] firing panel for {task_id} @ {commit}...",
              file=sys.stderr, flush=True)
        panel = run_panel(task_id, commit)
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = OUT_DIR / f"{stamp}_{task_id}_panel20.md"
        out_path.write_text(_format_report(panel), encoding="utf-8")
        rollup_rows.append((task_id, commit, panel))
        pv = panel.get("panel_verdict", "ERROR")
        print(f"[w11-sweep] {task_id}: {pv} "
              f"mean={panel.get('mean_confidence', 0)} "
              f"({panel.get('elapsed_sec', 0)}s)",
              file=sys.stderr, flush=True)

    elapsed = time.monotonic() - started
    print(f"\n[w11-sweep] total elapsed: {elapsed:.0f}s "
          f"({len(W11_TASKS)} rows)",
          file=sys.stderr, flush=True)

    # Write rollup
    rollup_lines = [
        "# W11 20-agent retroactive panel audit — rollup",
        "",
        f"_Swept {len(W11_TASKS)} W11 rows; elapsed {elapsed:.0f}s "
        f"({datetime.now(timezone.utc).isoformat()})_",
        "",
        "## Per-row verdicts",
        "",
        "| Row | Commit | Verdict | Mean Conf | Pass / Total | Notes |",
        "|---|---|---|---|---|---|",
    ]
    pass_count = 0
    for task_id, commit, panel in rollup_rows:
        pv = panel.get("panel_verdict", "ERROR")
        mean = panel.get("mean_confidence", 0)
        pc = panel.get("pass_count", 0)
        sp = panel.get("successful_personas", 0)
        tp = panel.get("total_personas", 0)
        notes = ""
        if "error" in panel:
            notes = panel["error"][:60]
        rollup_lines.append(
            f"| {task_id} | {commit} | {pv} | {mean} | {pc}/{sp} (of {tp}) | {notes} |"
        )
        if pv == "PASS":
            pass_count += 1
    rollup_lines.extend([
        "",
        f"## Summary: {pass_count}/{len(W11_TASKS)} rows panel-PASS",
        "",
        "(Per-row detail at the timestamped files in this directory.)",
    ])
    ROLLUP_PATH.write_text("\n".join(rollup_lines), encoding="utf-8")
    print(f"[w11-sweep] rollup: {ROLLUP_PATH}", file=sys.stderr)
    return 0 if pass_count == len(W11_TASKS) else 1


if __name__ == "__main__":
    sys.exit(main())
