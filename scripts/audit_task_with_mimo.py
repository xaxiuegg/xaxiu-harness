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
# W7-AUDIT-POLICY 2026-05-23: operator extended the audit gate to all
# Wn waves.  When the task_id begins with W7-, prefer the wave-7 plan;
# generalised pattern picks the right plan by ID prefix.
_PLAN_BY_TASK_PREFIX = {
    "W6-": "spec/wave-6-plan.md",
    "A1": "spec/wave-6-plan.md",   # W6 historic single-letter ids
    "A1-": "spec/wave-6-plan.md",
    "A2": "spec/wave-6-plan.md",
    "A3": "spec/wave-6-plan.md",
    "B1": "spec/wave-6-plan.md",
    "B2": "spec/wave-6-plan.md",
    "B3": "spec/wave-6-plan.md",
    "C1": "spec/wave-6-plan.md",
    "C2": "spec/wave-6-plan.md",
    "W7-": "spec/wave-7-plan.md",
}


def _resolve_plan_path(task_id: str, override: str | None) -> Path:
    """Pick the right plan file for *task_id* unless --plan overrides."""
    if override:
        return Path(override)
    for prefix, plan in _PLAN_BY_TASK_PREFIX.items():
        if task_id == prefix.rstrip("-") or task_id.startswith(prefix):
            return Path(plan)
    return PLAN_PATH  # default fallback
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

# Diff (first 16000 chars)

```
{diff_excerpt}
```

# Current state of modified files (post-commit)

These are the FULL CURRENT CONTENTS of each modified file after the
commit landed.  Use this to verify the implementation actually does
what the diff suggests (the diff may be misleading or partial).

{file_contents}

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
    # W6-A1.2-followup: raised from 4000 → 16000 chars after MiMo
    # audit STOPped with "diff missing" complaint on a 203-line commit.
    # MiMo's 131K input window has plenty of room for richer context.
    diff_excerpt = diff[:16000] + ("..." if len(diff) > 16000 else "")
    # Pull the current contents of each modified file so the auditor
    # sees the actual post-commit state (not just delta).
    file_list_raw = _run(["show", "--name-only", "--format=", full_sha]).strip()
    modified_files = [p for p in file_list_raw.splitlines() if p.strip()]
    file_contents_blocks: list[str] = []
    # Limit total file-content budget to ~12KB so prompt+diff stays
    # under MiMo's 60s gateway timeout for small reasoning tasks.
    per_file_budget = 3000
    for rel in modified_files[:4]:  # cap at 4 files
        path = Path(rel)
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(content) > per_file_budget:
            content = content[:per_file_budget] + f"\n... [+{len(content) - per_file_budget} chars truncated]"
        file_contents_blocks.append(f"## {rel}\n\n```\n{content}\n```")
    file_contents = "\n\n".join(file_contents_blocks) if file_contents_blocks else "(none)"
    return {
        "sha": sha_val,
        "author": author,
        "date": date,
        "message": message,
        "diffstat": diffstat,
        "diff_excerpt": diff_excerpt,
        "file_contents": file_contents,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", help="Wn task ID (e.g. A1, A2, W7-MUTATION-WORKER)")
    parser.add_argument("--commit", default="HEAD",
                        help="Commit SHA to audit (default HEAD).")
    parser.add_argument("--plan", default=None,
                        type=str,
                        help="Override the plan file.  Default: auto-pick "
                        "by task_id prefix (W7- → spec/wave-7-plan.md, "
                        "else spec/wave-6-plan.md).")
    args = parser.parse_args()

    # W7-AUDIT-POLICY: auto-resolve the plan path from task_id prefix
    # unless --plan overrides.
    plan_path = _resolve_plan_path(args.task_id, args.plan)
    if not plan_path.exists():
        print(f"plan not found: {plan_path}", file=sys.stderr)
        return 2

    plan_text = plan_path.read_text(encoding="utf-8")
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
        file_contents=info.get("file_contents", "(none)"),
    )

    print(f"[audit] task={args.task_id} sha={info['sha'][:12]} "
          f"prompt={len(prompt)} chars", flush=True)

    # Primary: MiMo (operator-specified auditor).
    # Fallback: DeepSeek (W5-MM streaming, reliable, pay-per-token but
    # audits are infrequent + small).  Mirrors worker.py fallback chain.
    auditor_used = "mimo"
    try:
        eng = get_engine("mimo", prefer_dpapi=False)
    except RuntimeError as exc:
        print(f"engine init failed: {exc}", file=sys.stderr)
        return 2
    started = time.monotonic()
    resp = eng.dispatch(prompt, "mimo-v2.5-pro", {"max_tokens": 8_000})
    latency = int((time.monotonic() - started) * 1000)

    # W6-A2 audit-script hardening 2026-05-23: MiMo's content filter
    # rejects prompts that mention API keys verbatim, returning a
    # response like "The request was rejected because it was
    # considered high risk".  That's a success=True text response,
    # so the old fallback gate (only success=False) didn't fire.
    # Also fall back when the response can't possibly be a JSON
    # audit verdict — no JSON braces or no "confidence" field.
    _mimo_rejected = (
        bool(resp.text)
        and ("rejected" in resp.text.lower()
             and "high risk" in resp.text.lower())
    )
    _mimo_unparseable = (
        bool(resp.text)
        and "{" not in resp.text  # no chance of JSON
    )
    if (not resp.success
            or not (resp.text or "").strip()
            or _mimo_rejected
            or _mimo_unparseable):
        reason = (
            "rejected by content filter" if _mimo_rejected
            else "unparseable text response" if _mimo_unparseable
            else resp.error
        )
        print(f"[audit] MiMo failed ({latency}ms): {reason}; "
              f"falling back to DeepSeek...", file=sys.stderr)
        try:
            eng = get_engine("deepseek", prefer_dpapi=False)
            fb_started = time.monotonic()
            resp = eng.dispatch(prompt, "deepseek-v4-flash", {"max_tokens": 8_000})
            latency += int((time.monotonic() - fb_started) * 1000)
            auditor_used = "deepseek (fallback)"
        except RuntimeError as exc:
            print(f"DeepSeek init failed: {exc}", file=sys.stderr)
            return 2

    if not resp.success or not (resp.text or "").strip():
        print(f"[audit] BOTH engines failed ({latency}ms): {resp.error}",
              file=sys.stderr)
        return 2

    print(f"[audit] auditor: {auditor_used} ({latency}ms total)", flush=True)
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
