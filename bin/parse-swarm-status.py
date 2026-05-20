"""Parse xaxiu-swarm dispatch output and classify the outcome.

Used by the integrating supervisor in the autonomous dev loop. Reads a
swarm dispatch's output file (the one Bash's run_in_background writes
to) and returns a structured classification plus the rationale.

Usage:
    python bin/parse-swarm-status.py <output-file> [--expect-edits-in <path> ...]

Outputs JSON to stdout:
    {
      "outcome": "success|timeout|prose_not_edits|refusal|api_error|unknown",
      "backend": "kimi|kimi-api|deepseek|...",
      "elapsed_seconds": int | null,
      "exit_code": int | null,
      "files_modified": [...],     # from git diff if --expect-edits-in given
      "rationale": "<one-sentence explanation>"
    }
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_STATUS_LINE = re.compile(r"^status:\s+(\w+)(?:\s+\(elapsed\s+([\d.]+)s\))?", re.MULTILINE)
_BACKEND_LINE = re.compile(r"^backend:\s+(\S+)", re.MULTILINE)
_EXIT_LINE = re.compile(r"^exit:\s+(\d+)", re.MULTILINE)
_REFUSAL = re.compile(r"\b(i (can't|cannot)|i'm sorry,? but|i (am )?not able)\b", re.IGNORECASE)
_API_ERROR = re.compile(r"\b(api.error|401|403|429|5\d\d (server|error))\b", re.IGNORECASE)
_CODE_FENCE = re.compile(r"^```", re.MULTILINE)


def _files_modified_in(paths: list[str]) -> list[str]:
    """Files changed in working tree under the given paths (vs HEAD)."""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--"] + paths,
            capture_output=True, text=True, check=False,
        )
        return [f for f in out.stdout.splitlines() if f]
    except FileNotFoundError:
        return []


def classify(text: str, expect_paths: list[str]) -> dict:
    backend_m = _BACKEND_LINE.search(text)
    status_m = _STATUS_LINE.search(text)
    exit_m = _EXIT_LINE.search(text)

    backend = backend_m.group(1) if backend_m else None
    status = status_m.group(1) if status_m else None
    elapsed = float(status_m.group(2)) if status_m and status_m.group(2) else None
    exit_code = int(exit_m.group(1)) if exit_m else None

    files_modified = _files_modified_in(expect_paths) if expect_paths else []

    # Decision tree
    if status == "timeout":
        outcome = "timeout"
        rationale = f"swarm reported timeout after {elapsed}s"
    elif status == "success" and (files_modified or not expect_paths):
        outcome = "success"
        rationale = f"swarm exit 0; {len(files_modified)} files modified"
    elif status == "success" and expect_paths and not files_modified:
        # Status says success but no files changed — the prose-not-edits trap
        # If there are code fences in the output, that confirms it produced
        # code text without applying it.
        if _CODE_FENCE.search(text):
            outcome = "prose_not_edits"
            rationale = "swarm exit 0 but no files in expected paths changed; output contains code fences (prose-not-edits trap)"
        else:
            outcome = "prose_not_edits"
            rationale = "swarm exit 0 but no files in expected paths changed"
    elif _REFUSAL.search(text):
        outcome = "refusal"
        rationale = "engine output matches refusal pattern"
    elif _API_ERROR.search(text):
        outcome = "api_error"
        rationale = "engine output mentions HTTP error"
    elif exit_code and exit_code != 0:
        outcome = "unknown_failure"
        rationale = f"non-zero exit ({exit_code}) without recognized cause"
    else:
        outcome = "unknown"
        rationale = "could not classify (no status/exit/refusal markers found)"

    return {
        "outcome": outcome,
        "backend": backend,
        "elapsed_seconds": elapsed,
        "exit_code": exit_code,
        "files_modified": files_modified,
        "rationale": rationale,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify a xaxiu-swarm dispatch output.")
    parser.add_argument("output_file", help="Path to the swarm dispatch output file.")
    parser.add_argument(
        "--expect-edits-in", action="append", default=[],
        help="Repeatable: paths where the dispatch should have produced edits. "
             "If none changed under these paths, classifies as prose_not_edits.",
    )
    args = parser.parse_args(argv)

    path = Path(args.output_file)
    if not path.exists():
        print(json.dumps({"outcome": "missing", "rationale": f"file not found: {path}"}), file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8", errors="replace")
    result = classify(text, args.expect_edits_in)
    print(json.dumps(result, indent=2))

    # Exit code reflects classification severity for shell integration
    return {
        "success": 0,
        "unknown": 1,
        "prose_not_edits": 3,
        "refusal": 3,
        "timeout": 3,
        "api_error": 3,
        "unknown_failure": 4,
        "missing": 5,
    }.get(result["outcome"], 1)


if __name__ == "__main__":
    sys.exit(main())
