"""W6 MiMo audit gate — runs after every Wave 6 task lands.

Operator directive 2026-05-23: between every Wave 6 task, fire a
single MiMo Pro v2.5 agent to audit the just-shipped commit against
the task's acceptance criteria.  If confidence < 0.7, STOP and
surface to operator.  Pass (≥ 0.7) → proceed to next task.

This addresses the "ship-without-review" pattern surfaced by the
5-MiMo session review at coord/reviews/external/20260523T140257Z_*.md.

Usage:
    python scripts/audit_task_with_mimo.py <task-id> [--commit <sha>]

Reads acceptance criteria from spec/wave-6-plan.md by task-id
(e.g. "A1", "B2").  If --commit omitted, uses HEAD.

Writes:
    coord/reviews/audits/<stamp>_<task-id>_audit.md

Exit codes:
    0  audit passed (confidence ≥ 0.7)
    1  audit failed (confidence < 0.7); operator review required
    2  setup error (task-id not found / engine init failed)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


PLAN_PATH = Path("spec/wave-6-plan.md")
OUT_DIR = Path("coord/reviews/audits")
CONFIDENCE_GATE = 0.7


AUDIT_PROMPT = """\
You are auditing a single Wave 6 task that just landed in xaxiu-harness.

# Wave 6 task: {task_id}

# Acceptance criteria (from spec/wave-6-plan.md)

{acceptance}

# Commit context

SHA:    {sha}
Author: {author}
Date:   {date}
Message:
{message}

# Files changed

{diffstat}

# Diff (first 4000 chars)

```
{diff_excerpt}
```

# Your task

Audit this commit against the acceptance criteria.  Be skeptical.
The harness has a documented history of "ship-without-review" bugs
(see W5-V Kimi 0/10, W4-K zero-token ledger).  Specifically check:

1. Are ALL acceptance criteria demonstrably met by this commit?
2. Are there tests for the new behavior, OR is the test count just
   passing because of stubs/mocks that rubber-stamp?
3. Does the commit introduce new debt (dup'd logic, missing
   abstraction, magic numbers, untested error paths)?
4. Is there evidence this code was ACTUALLY exercised end-to-end
   (smoke output, real-API run, integration trace) — not just unit
   tests against happy-path mocks?

Output **JSON only**, no preamble, no markdown fence:

{{
  "task_id": "{task_id}",
  "criteria_met": true/false,
  "criteria_gaps": ["specific gap 1", "..."],
  "test_quality_concerns": ["..."],
  "new_debt": ["..."],
  "evidence_of_e2e_exercise": "describe what evidence is present, or 'none'",
  "confidence": 0.0,
  "verdict": "PASS" | "STOP — operator review required",
  "one_line_summary": "..."
}}

Confidence scale:
  0.9-1.0  All criteria met, real-world exercise documented, no debt
  0.7-0.9  Criteria met but one minor concern (acceptable to proceed)
  0.5-0.7  Criteria partially met OR significant test-quality concern
  0.0-0.5  Criteria not met OR critical debt introduced

Gate: confidence < 0.7 = STOP.
"""


def extract_acceptance(plan_text: str, task_id: str) -> str | None:
    """Find the **Acceptance** section under #### <task-id> in the plan."""
    # Match the task header (e.g. "#### A1 — ...") and capture until the next
    # #### header or end-of-doc.
    pat = re.compile(
        rf"####\s*{re.escape(task_id)}[^\n]*\n(.*?)(?=\n####|\nW6-CLOSEOUT|\Z)",
        re.DOTALL,
    )
    m = pat.search(plan_text)
    if not m:
        return None
    section = m.group(1)
    # Now find **Acceptance**: section within
    acc_pat = re.compile(r"\*\*Acceptance\*\*:\s*\n(.*?)(?=\n\n###|\n####|\Z)", re.DOTALL)
    am = acc_pat.search(section)
    if not am:
        return section.strip()  # fallback to whole task section
    return am.group(1).strip()


def git_commit_info(sha: str = "HEAD") -> dict:
    """Pull SHA + author + date + message + diffstat + diff excerpt for a commit."""
    def _run(args: list[str]) -> str:
        try:
            return subprocess.run(
                ["git"] + args, capture_output=True, text=True, check=False,
            ).stdout
        except OSError:
            return ""
    full_sha = _run(["rev-parse", sha]).strip()
    info_lines = _run(["show", "--no-patch", "--format=%H%n%an%n%aI%n%s%n%n%b", full_sha]).splitlines()
    if len(info_lines) >= 4:
        sha_val = info_lines[0]
        author = info_lines[1]
        date = info_lines[2]
        message = "\n".join(info_lines[3:]).strip()
    else:
        sha_val = full_sha
        author = "?"
        date = "?"
        message = "(no message)"
    diffstat = _run(["show", "--stat", "--format=", full_sha]).strip()
    diff = _run(["show", "--format=", full_sha])
    diff_excerpt = diff[:4000] + ("..." if len(diff) > 4000 else "")
    return {
        "sha": sha_val,
        "author": author,
        "date": date,
        "message": message,
        "diffstat": diffstat,
        "diff_excerpt": diff_excerpt,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", help="Wave 6 task ID (A1, A2, B1, etc.)")
    parser.add_argument("--commit", default="HEAD",
                        help="Commit SHA to audit (default HEAD).")
    parser.add_argument("--plan", default=str(PLAN_PATH),
                        type=Path,
                        help="Wave 6 plan file (default spec/wave-6-plan.md).")
    args = parser.parse_args()

    if not args.plan.exists():
        print(f"plan not found: {args.plan}", file=sys.stderr)
        return 2

    plan_text = args.plan.read_text(encoding="utf-8")
    acceptance = extract_acceptance(plan_text, args.task_id)
    if not acceptance:
        print(f"task {args.task_id} not found in plan", file=sys.stderr)
        return 2

    info = git_commit_info(args.commit)
    prompt = AUDIT_PROMPT.format(
        task_id=args.task_id,
        acceptance=acceptance,
        sha=info["sha"][:12],
        author=info["author"],
        date=info["date"],
        message=info["message"],
        diffstat=info["diffstat"][:2000],
        diff_excerpt=info["diff_excerpt"],
    )

    print(f"[audit] task={args.task_id} sha={info['sha'][:12]} "
          f"prompt={len(prompt)} chars", flush=True)
    try:
        eng = get_engine("mimo", prefer_dpapi=False)
    except RuntimeError as exc:
        print(f"engine init failed: {exc}", file=sys.stderr)
        return 2
    started = time.monotonic()
    resp = eng.dispatch(prompt, "mimo-v2.5-pro", {"max_tokens": 8_000})
    latency = int((time.monotonic() - started) * 1000)

    if not resp.success or not (resp.text or "").strip():
        print(f"[audit] dispatch failed ({latency}ms): {resp.error}",
              file=sys.stderr)
        return 2

    text = resp.text.strip()
    # Extract JSON
    m = re.search(r"\{[\s\S]*\}", text)
    parsed: dict = {}
    if m:
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            parsed = {}

    confidence = float(parsed.get("confidence", 0.0)) if parsed else 0.0
    verdict = parsed.get("verdict", "?")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = OUT_DIR / f"{stamp}_{args.task_id}_audit.md"
    body = (
        f"<!-- engine=mimo model=mimo-v2.5-pro task={args.task_id} "
        f"sha={info['sha'][:12]} latency_ms={latency} "
        f"confidence={confidence} verdict={verdict} -->\n\n"
        f"# Wave 6 MiMo audit — task {args.task_id}\n\n"
        f"- Commit: `{info['sha'][:12]}` by {info['author']} on {info['date']}\n"
        f"- Message: {info['message'].splitlines()[0] if info['message'] else '(empty)'}\n"
        f"- Confidence: **{confidence:.2f}**\n"
        f"- Verdict: **{verdict}**\n"
        f"- Latency: {latency}ms\n\n"
        f"## Raw MiMo audit response\n\n```\n{text}\n```\n"
    )
    out_path.write_text(body, encoding="utf-8")

    passed = confidence >= CONFIDENCE_GATE
    print(f"\n[audit] {args.task_id}: confidence={confidence:.2f}  "
          f"verdict={verdict}  → {'PASS' if passed else 'STOP'}")
    print(f"[audit] report: {out_path}")
    if not passed:
        print(f"\n*** STOP — confidence {confidence:.2f} < gate {CONFIDENCE_GATE}.")
        print(f"*** Operator review required before next task.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
