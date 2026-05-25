"""W6 MiMo audit gate — runs after every Wave 6 task lands.

Operator directive 2026-05-23: between every Wave 6 task, fire a
single MiMo Pro v2.5 agent to audit the just-shipped commit against
the task's acceptance criteria.  If confidence < 0.7, STOP and
surface to operator.  Pass (≥ 0.7) → proceed to next task.

This addresses the "ship-without-review" pattern surfaced by the
5-MiMo session review at coord/reviews/external/20260523T140257Z_*.md.

W9-AUDIT-NONDETERMINISM-AVG 2026-05-24: ``--avg-of-N`` flag runs the
audit N times in parallel and gates on the MEAN confidence rather
than a single run.  Master audit found 3 W8 rows flipped PASS↔STOP
across sweeps with no code change; the single-run gate is partly
noise.  N=3 cancels most of that.

Usage:
    python scripts/audit_task_with_mimo.py <task-id> [--commit <sha>]
    python scripts/audit_task_with_mimo.py <task-id> --avg-of-N 3

Reads acceptance criteria from spec/wave-6-plan.md by task-id
(e.g. "A1", "B2").  If --commit omitted, uses HEAD.

Writes:
    coord/reviews/audits/<stamp>_<task-id>_audit.md             (single)
    coord/reviews/audits/<stamp>_<task-id>_audit_avgN.md        (--avg-of-N>1)

Exit codes:
    0  audit passed (mean confidence ≥ 0.7)
    1  audit failed (mean confidence < 0.7); operator review required
    2  setup error (task-id not found / engine init failed)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


PLAN_PATH = Path("spec/wave-6-plan.md")
STATUS_CSV_PATH = Path("coord/STATUS.csv")
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
    "W8-": "spec/wave-8-plan.md",
    "W9-": "spec/wave-9-plan.md",
    "W10-": "spec/wave-10-plan.md",
    "W11-": "spec/wave-11-plan.md",
}

# W13-AUDIT-INFRA-W13-PLUS 2026-05-25: W12+ work migrated to
# coord/STATUS.csv + coord/CURRENT_PLAN.md — there is no spec/wave-13-
# plan.md.  Before this fallback every W13 row shipped this week
# returned `ERROR: task W13-FOO not found in plan spec\wave-6-plan.md`
# (fell through to the default and obviously wasn't there).  The
# generic regex picks spec/wave-N-plan.md if that file happens to
# exist, else routes to STATUS.csv where load_acceptance() reads the
# Notes column.
_WAVE_PREFIX_RE = re.compile(r"^W(\d+)-")


def _resolve_plan_path(task_id: str, override: str | None) -> Path:
    """Pick the right plan file for *task_id* unless --plan overrides.

    Resolution order:
      1. ``override`` if provided.
      2. Explicit prefix in _PLAN_BY_TASK_PREFIX (W6-, A1, ..., W11-).
      3. Generic ``W<N>-`` match: ``spec/wave-N-plan.md`` if it exists,
         else ``coord/STATUS.csv``.
      4. Fallback to ``PLAN_PATH`` (the W6 plan).
    """
    if override:
        return Path(override)
    for prefix, plan in _PLAN_BY_TASK_PREFIX.items():
        if task_id == prefix.rstrip("-") or task_id.startswith(prefix):
            return Path(plan)
    m = _WAVE_PREFIX_RE.match(task_id)
    if m:
        wave_num = m.group(1)
        candidate = Path(f"spec/wave-{wave_num}-plan.md")
        if candidate.exists():
            return candidate
        return STATUS_CSV_PATH
    return PLAN_PATH  # default fallback
OUT_DIR = Path("coord/reviews/audits")
CONFIDENCE_GATE = 0.7


AUDIT_PROMPT = """\
You are auditing a single Wave 6 task that just landed in xaxiu-harness.

# Wave 6 task: {task_id}

# Acceptance criteria (from {plan_path})

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


def _load_acceptance_from_status_csv(task_id: str, csv_path: Path) -> str | None:
    """Pull the Notes column of *task_id*'s row + frame it as acceptance.

    STATUS.csv rows don't have a structured `**Acceptance**:` bullet
    block — their Notes column holds free-form prose describing what
    shipped (and implicitly what was expected to ship).  We frame it
    with the row's metadata so the auditor knows the format differs
    from the spec/wave-N-plan.md style and can interpret accordingly.

    Returns the framed markdown text, or None if no matching row.
    """
    if not csv_path.exists():
        return None
    import csv as _csv
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = _csv.DictReader(fh)
        for row in reader:
            if (row.get("ID") or "").strip() != task_id:
                continue
            title = (row.get("Title") or "").strip()
            category = (row.get("Category") or "").strip()
            status = (row.get("Status") or "").strip()
            owner = (row.get("Owner") or "").strip()
            updated = (row.get("Updated") or "").strip()
            notes = (row.get("Notes") or "").strip() or "(no notes — empty)"
            return (
                f"**Source**: coord/STATUS.csv "
                f"(W12+ tasks track here, not in spec/wave-N-plan.md)\n\n"
                f"- ID: `{task_id}`\n"
                f"- Title: {title}\n"
                f"- Category: {category}\n"
                f"- Status: {status} (Owner: {owner}, Updated: {updated})\n\n"
                f"**Acceptance criteria / shipped notes** "
                f"(verbatim from Notes column — STATUS.csv rows do not "
                f"have a structured `**Acceptance**:` block; the Notes "
                f"column describes what the row was supposed to land):\n\n"
                f"{notes}"
            )
    return None


def load_acceptance(task_id: str, plan_path: Path) -> str | None:
    """Load acceptance-criteria text for *task_id* from *plan_path*.

    Dispatches on the source format:
      * ``coord/STATUS.csv`` (or any ``.csv``) → ``_load_acceptance_from_status_csv``.
      * Otherwise → reads the file and calls ``extract_acceptance``.

    Returns None when the row/section is missing or the file does not
    exist.  Callers use None as the "task not found in plan" signal.
    """
    if plan_path.suffix.lower() == ".csv" or plan_path.name == "STATUS.csv":
        return _load_acceptance_from_status_csv(task_id, plan_path)
    if not plan_path.exists():
        return None
    plan_text = plan_path.read_text(encoding="utf-8")
    return extract_acceptance(plan_text, task_id)


def _run_git(args: list[str]) -> str:
    """Module-level git runner (was nested in git_commit_info)."""
    try:
        return subprocess.run(
            ["git"] + args, capture_output=True, text=True, check=False,
        ).stdout
    except OSError:
        return ""


def find_latest_commit_for_task(task_id: str,
                                lookback: int = 50) -> str | None:
    """Find the most recent commit whose subject mentions *task_id*.

    W10-AUDIT-FOLLOWUP-COMMIT-POLICY: when an audit STOPed and a
    followup commit landed, --reaudit uses this to pick the followup
    commit's SHA instead of the original one.  Looks back through
    the last *lookback* commits (50 by default — enough to span a
    wave's worth of work).

    Token-boundary rule: ``task_id`` must appear as a whole token in
    the subject.  Accepts hyphen-suffixes (W10-CLI matches
    W10-CLI-TIMEOUT-BUDGET because followup commits often append
    suffixes).  Rejects bare alphanumeric suffixes (W10-FO does NOT
    match W10-FOO).  Rejects substring matches with non-boundary
    prefixes (W10-FOO does NOT match XW10-FOO).
    """
    out = _run_git(["log", "-n", str(lookback), "--format=%H %s"])
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # Split SHA off the front first so all boundary math is
        # local to the subject string.
        if " " not in line:
            continue
        sha, subject = line.split(" ", 1)
        idx = subject.find(task_id)
        if idx == -1:
            continue
        end_idx = idx + len(task_id)
        char_before = subject[idx - 1] if idx > 0 else " "
        char_after = subject[end_idx] if end_idx < len(subject) else " "
        # Pre-boundary: reject if previous char is alphanumeric or hyphen
        # (means task_id is a tail of a longer id).
        if char_before.isalnum() or char_before == "-":
            continue
        # Post-boundary: hyphen ok (suffix expansion), alphanumeric rejects.
        if char_after.isalnum():
            continue
        return sha
    return None


def resolve_commit_range(spec: str) -> list[str]:
    """Translate ``spec`` into a list of commit SHAs (oldest first).

    Accepts:
        "abc1234"       -> [abc1234]
        "abc..def"      -> commits in abc..def (oldest first; --reverse)
        "since:N"       -> last N commits ending at HEAD (oldest first)
        "HEAD~3..HEAD"  -> standard git range syntax also works

    Returns at most 20 SHAs to keep the diff aggregate bounded
    (prevents runaway audit prompts on very long ranges).
    """
    if spec.startswith("since:"):
        try:
            n = int(spec[len("since:"):])
        except ValueError:
            return []
        if n < 1:
            return []
        # git log -n N HEAD --format=%H (newest first), reverse for oldest first
        out = _run_git(["log", "-n", str(min(n, 20)),
                        "--format=%H", "HEAD"]).split()
        return list(reversed(out))
    if ".." in spec:
        # git range syntax — git log <range> --reverse --format=%H
        out = _run_git(["log", spec, "--reverse", "--format=%H"]).split()
        return out[:20]
    # Single SHA
    full = _run_git(["rev-parse", spec]).strip()
    return [full] if full else []


def git_commit_info(sha: str = "HEAD") -> dict:
    """Single-commit info — preserved for legacy callers.

    For multi-commit deliverables use ``git_commits_info(shas)``.
    """
    return git_commits_info([sha])


def git_commits_info(shas: list[str]) -> dict:
    """Pull SHA + author + date + message + diffstat + diff excerpt
    aggregated across *shas*.

    W9-AUDIT-ANCHOR-MULTI-COMMIT 2026-05-24: previously single-anchor
    only.  Multi-commit deliverables (e.g. W8-STOP-HOOK, W8-AUDIT-
    PROMPT) were mis-audited because the auditor only saw the first
    commit's diff.  This aggregates the diff + file content across
    every SHA in the deliverable.
    """
    if not shas:
        # Backward-compat: empty input behaves like HEAD lookup
        shas = ["HEAD"]
    _run = _run_git
    # Resolve all SHAs first
    full_shas: list[str] = []
    for s in shas:
        resolved = _run(["rev-parse", s]).strip()
        if resolved:
            full_shas.append(resolved)
    if not full_shas:
        full_shas = shas[:]

    # Aggregate message: head commit's message + "+ N more commit(s)"
    head_sha = full_shas[-1]  # newest in the range (or only)
    info_lines = _run(["show", "--no-patch",
                       "--format=%H%n%an%n%aI%n%s%n%n%b",
                       head_sha]).splitlines()
    if len(info_lines) >= 4:
        sha_val = info_lines[0]
        author = info_lines[1]
        date = info_lines[2]
        message = "\n".join(info_lines[3:]).strip()
    else:
        sha_val = head_sha
        author = "?"
        date = "?"
        message = "(no message)"
    if len(full_shas) > 1:
        all_subjects = []
        for s in full_shas:
            subj = _run(["show", "--no-patch", "--format=%s", s]).strip()
            if subj:
                all_subjects.append(f"  - {s[:12]}: {subj}")
        message = (
            message
            + f"\n\n[multi-commit deliverable — {len(full_shas)} commits]\n"
            + "\n".join(all_subjects)
        )

    # Aggregate diffstat + diff across all commits (oldest first so
    # the auditor sees the natural history order)
    diffstat_parts = []
    diff_parts = []
    for s in full_shas:
        ds = _run(["show", "--stat", "--format=", s]).strip()
        if ds:
            diffstat_parts.append(f"# {s[:12]}\n{ds}")
        d = _run(["show", "--format=", s])
        if d:
            diff_parts.append(f"# === commit {s[:12]} ===\n{d}")
    diffstat = "\n\n".join(diffstat_parts)
    diff = "\n\n".join(diff_parts)
    # W6-A1.2-followup: raised from 4000 → 16000 chars after MiMo
    # audit STOPped with "diff missing" complaint on a 203-line commit.
    # W8-AUDIT-PROMPT 2026-05-23: raised from 16000 → 48000 chars after
    # the W7 retroactive sweep hit 4/9 STOPs because the auditor
    # objected to truncated diffs.  MiMo's 131K input window easily
    # handles 48K diff + 64K file content + ~10K prompt boilerplate.
    # If diff still exceeds 48K, prefer head + tail with a marker so
    # the auditor sees the beginning AND end of the change (not just
    # the first 48K of a 100K diff).
    _DIFF_LIMIT = 48_000
    if len(diff) > _DIFF_LIMIT:
        head_chars = int(_DIFF_LIMIT * 0.7)
        tail_chars = _DIFF_LIMIT - head_chars
        diff_excerpt = (
            diff[:head_chars]
            + f"\n\n... [{len(diff) - _DIFF_LIMIT} chars elided "
            "between head and tail] ...\n\n"
            + diff[-tail_chars:]
        )
    else:
        diff_excerpt = diff
    # Pull the current contents of each modified file across the
    # whole range so the auditor sees the actual post-commit state
    # (not just delta).  Take the union of files touched anywhere
    # in the range; dedupe preserves first-seen order.
    seen: set[str] = set()
    modified_files: list[str] = []
    for s in full_shas:
        file_list_raw = _run(["show", "--name-only", "--format=", s]).strip()
        for p in file_list_raw.splitlines():
            p = p.strip()
            if p and p not in seen:
                seen.add(p)
                modified_files.append(p)
    file_contents_blocks: list[str] = []
    # W8-AUDIT-PROMPT 2026-05-23: per-file budget raised 3000 → 8000;
    # file cap raised 4 → 10.  Same MiMo 131K-window justification as
    # the diff bump.  Files larger than 8K use the head+tail strategy
    # so the auditor sees the file's structure top + key changes
    # bottom (most Python modules put the file's primary exported
    # function near the end after helpers).
    _PER_FILE_BUDGET = 8_000
    for rel in modified_files[:10]:
        path = Path(rel)
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(content) > _PER_FILE_BUDGET:
            head = int(_PER_FILE_BUDGET * 0.6)
            tail = _PER_FILE_BUDGET - head
            content = (
                content[:head]
                + f"\n\n... [{len(content) - _PER_FILE_BUDGET} chars "
                "elided between head and tail] ...\n\n"
                + content[-tail:]
            )
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


# -- W9-AUDIT-NONDETERMINISM-AVG helpers -----------------------------------


@dataclass
class AuditRun:
    """One run of the audit.  Multiple runs aggregate into AuditSummary."""
    confidence: float
    verdict: str
    text: str
    parsed: dict = field(default_factory=dict)
    latency_ms: int = 0
    auditor_used: str = "mimo"
    success: bool = True
    error: str | None = None


@dataclass
class AuditSummary:
    """Aggregate of N audit runs.  Pure data; no I/O."""
    runs: list[AuditRun]
    mean_confidence: float
    stdev_confidence: float  # 0.0 if N < 2
    min_confidence: float
    max_confidence: float
    verdicts: list[str]
    pass_count: int
    total_runs: int
    successful_runs: int

    @property
    def passed(self) -> bool:
        """Gate: mean ≥ CONFIDENCE_GATE AND at least one successful run."""
        return self.successful_runs > 0 and self.mean_confidence >= CONFIDENCE_GATE


def aggregate_runs(runs: list[AuditRun]) -> AuditSummary:
    """Pure aggregation of N runs into a summary.  Testable in isolation."""
    successful = [r for r in runs if r.success]
    confidences = [r.confidence for r in successful]
    if not confidences:
        return AuditSummary(
            runs=runs,
            mean_confidence=0.0,
            stdev_confidence=0.0,
            min_confidence=0.0,
            max_confidence=0.0,
            verdicts=[r.verdict for r in runs],
            pass_count=0,
            total_runs=len(runs),
            successful_runs=0,
        )
    mean = statistics.mean(confidences)
    stdev = statistics.stdev(confidences) if len(confidences) >= 2 else 0.0
    return AuditSummary(
        runs=runs,
        mean_confidence=mean,
        stdev_confidence=stdev,
        min_confidence=min(confidences),
        max_confidence=max(confidences),
        verdicts=[r.verdict for r in successful],
        pass_count=sum(1 for c in confidences if c >= CONFIDENCE_GATE),
        total_runs=len(runs),
        successful_runs=len(successful),
    )


def parse_audit_response(text: str) -> tuple[float, str, dict]:
    """Extract confidence + verdict + parsed-JSON from the engine's text.

    Returns (0.0, "?", {}) if no parseable JSON found.  Pure function.
    """
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return 0.0, "?", {}
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return 0.0, "?", {}
    confidence = float(parsed.get("confidence", 0.0))
    verdict = parsed.get("verdict", "?")
    return confidence, verdict, parsed


def _dispatch_with_fallback(prompt: str, max_tokens: int = 8_000) -> AuditRun:
    """Run one DeepSeek audit, falling back to MiMo on failure.

    W10-MIMO-FILTER-INVESTIGATION 2026-05-25: primary swapped from
    MiMo to DeepSeek-v4-flash.  Every W9 audit hit MiMo's content
    filter (~60s/attempt × 3 in avg-of-3 = 3min wasted before
    DeepSeek fallback served the audit).  See
    coord/reviews/audit-engine-choice.md for the decision doc.

    MiMo retained as fallback so the pipeline still has engine
    redundancy if DeepSeek is unreachable.

    Returns AuditRun (success=False sets confidence=0.0 and error= reason).
    """
    auditor_used = "deepseek"
    started = time.monotonic()
    try:
        eng = get_engine("deepseek", prefer_dpapi=False)
    except RuntimeError as exc:
        return AuditRun(confidence=0.0, verdict="?", text="",
                        latency_ms=0, auditor_used="deepseek",
                        success=False, error=f"deepseek init failed: {exc}")
    resp = eng.dispatch(prompt, "deepseek-v4-flash", {"max_tokens": max_tokens})
    latency = int((time.monotonic() - started) * 1000)

    # Same defensive fallback gate as before: handle empty / unparseable
    # responses by trying the alternate engine.
    _unparseable = (
        bool(resp.text)
        and "{" not in resp.text  # no chance of JSON
    )
    if (not resp.success
            or not (resp.text or "").strip()
            or _unparseable):
        reason = (
            "unparseable text response" if _unparseable
            else resp.error
        )
        print(f"[audit] DeepSeek failed ({latency}ms): {reason}; "
              f"falling back to MiMo...", file=sys.stderr)
        try:
            eng = get_engine("mimo", prefer_dpapi=False)
            fb_started = time.monotonic()
            resp = eng.dispatch(prompt, "mimo-v2.5-pro", {"max_tokens": max_tokens})
            latency += int((time.monotonic() - fb_started) * 1000)
            auditor_used = "mimo (fallback)"
        except RuntimeError as exc:
            return AuditRun(confidence=0.0, verdict="?", text="",
                            latency_ms=latency, auditor_used="deepseek",
                            success=False, error=f"mimo init failed: {exc}")
        # Defensive: if MiMo also trips its content filter on the
        # fallback path, surface that explicitly.
        _mimo_rejected = (
            bool(resp.text)
            and ("rejected" in resp.text.lower()
                 and "high risk" in resp.text.lower())
        )
        if _mimo_rejected:
            return AuditRun(confidence=0.0, verdict="?", text=resp.text,
                            latency_ms=latency, auditor_used=auditor_used,
                            success=False,
                            error="both engines failed: MiMo content "
                                  "filter rejected prompt")

    if not resp.success or not (resp.text or "").strip():
        return AuditRun(confidence=0.0, verdict="?", text="",
                        latency_ms=latency, auditor_used=auditor_used,
                        success=False,
                        error=f"both engines failed: {resp.error}")

    text = resp.text.strip()
    confidence, verdict, parsed = parse_audit_response(text)
    return AuditRun(
        confidence=confidence, verdict=verdict, text=text,
        parsed=parsed, latency_ms=latency, auditor_used=auditor_used,
        success=True,
    )


def _format_single_report(task_id: str, info: dict, run: AuditRun) -> str:
    """Format the report body for a single (N=1) audit."""
    confidence = run.confidence
    verdict = run.verdict
    text = run.text
    latency = run.latency_ms
    return (
        f"<!-- engine=mimo model=mimo-v2.5-pro task={task_id} "
        f"sha={info['sha'][:12]} latency_ms={latency} "
        f"confidence={confidence} verdict={verdict} -->\n\n"
        f"# Wave 6 MiMo audit — task {task_id}\n\n"
        f"- Commit: `{info['sha'][:12]}` by {info['author']} on {info['date']}\n"
        f"- Message: {info['message'].splitlines()[0] if info['message'] else '(empty)'}\n"
        f"- Confidence: **{confidence:.2f}**\n"
        f"- Verdict: **{verdict}**\n"
        f"- Latency: {latency}ms\n\n"
        f"## Raw MiMo audit response\n\n```\n{text}\n```\n"
    )


def _format_avg_report(task_id: str, info: dict, summary: AuditSummary) -> str:
    """Format the report body for an N>1 averaged audit."""
    runs = summary.runs
    pass_str = "PASS" if summary.passed else "STOP"
    header = (
        f"<!-- engine=mimo model=mimo-v2.5-pro task={task_id} "
        f"sha={info['sha'][:12]} avg_of_n={summary.total_runs} "
        f"mean_confidence={summary.mean_confidence:.2f} "
        f"stdev_confidence={summary.stdev_confidence:.2f} "
        f"min={summary.min_confidence:.2f} max={summary.max_confidence:.2f} "
        f"pass_count={summary.pass_count}/{summary.total_runs} "
        f"successful_runs={summary.successful_runs}/{summary.total_runs} "
        f"verdict={pass_str} -->\n\n"
        f"# MiMo audit (avg of {summary.total_runs}) — task {task_id}\n\n"
        f"- Commit: `{info['sha'][:12]}` by {info['author']} on {info['date']}\n"
        f"- Message: {info['message'].splitlines()[0] if info['message'] else '(empty)'}\n"
        f"- Runs requested: {summary.total_runs}\n"
        f"- Runs successful: {summary.successful_runs}\n"
        f"- **Mean confidence: {summary.mean_confidence:.2f}** "
        f"(stdev {summary.stdev_confidence:.2f}, "
        f"min {summary.min_confidence:.2f}, max {summary.max_confidence:.2f})\n"
        f"- Per-run pass count (≥ {CONFIDENCE_GATE:.2f}): "
        f"{summary.pass_count}/{summary.total_runs}\n"
        f"- **Final verdict (mean-gated): {pass_str}**\n\n"
    )
    per_run_lines = []
    for idx, run in enumerate(runs, 1):
        if run.success:
            per_run_lines.append(
                f"### Run {idx} — confidence {run.confidence:.2f} "
                f"({run.verdict}) — auditor: {run.auditor_used} "
                f"({run.latency_ms}ms)\n\n```\n{run.text}\n```\n"
            )
        else:
            per_run_lines.append(
                f"### Run {idx} — FAILED — auditor: {run.auditor_used}\n\n"
                f"Error: {run.error}\n"
            )
    return header + "## Per-run details\n\n" + "\n".join(per_run_lines)


def _resolve_outpath(task_id: str, avg_of_n: int) -> Path:
    """Compose the output report path for this audit."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "_audit" if avg_of_n <= 1 else f"_audit_avg{avg_of_n}"
    return OUT_DIR / f"{stamp}_{task_id}{suffix}.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", help="Wn task ID (e.g. A1, A2, W7-MUTATION-WORKER)")
    parser.add_argument("--commit", default="HEAD",
                        help="Commit SHA to audit (default HEAD).  "
                        "Mutually exclusive with --commit-range / --since.")
    parser.add_argument("--commit-range", default=None,
                        help="W9-AUDIT-ANCHOR-MULTI-COMMIT: A..B git range "
                        "syntax — audits the diff aggregated across every "
                        "commit in the range (oldest first).  Use this for "
                        "multi-commit deliverables that the single-anchor "
                        "audit consistently STOPs on.")
    parser.add_argument("--since", type=int, default=None,
                        help="W9-AUDIT-ANCHOR-MULTI-COMMIT: last N commits "
                        "ending at HEAD.  Equivalent to --commit-range "
                        "HEAD~N..HEAD; capped at 20 commits.")
    parser.add_argument("--plan", default=None,
                        type=str,
                        help="Override the plan file.  Default: auto-pick "
                        "by task_id prefix (W7- → spec/wave-7-plan.md, "
                        "else spec/wave-6-plan.md).")
    parser.add_argument("--avg-of-N", dest="avg_of_n", type=int, default=1,
                        help="Run the audit N times in parallel and gate "
                        "on the MEAN confidence (W9-AUDIT-NONDETERMINISM-AVG). "
                        "N=1 keeps legacy single-run behavior.  N>=3 "
                        "recommended for noise-sensitive verdicts.")
    parser.add_argument("--reaudit", action="store_true",
                        help="W10-AUDIT-FOLLOWUP-COMMIT-POLICY: when a "
                        "previous audit STOPed and a followup commit "
                        "addressed the gaps, --reaudit picks the most "
                        "recent commit whose subject mentions this "
                        "task_id (looking back up to 50 commits) and "
                        "audits THAT commit instead of --commit.  Use "
                        "after landing a followup so the audit verdict "
                        "tracks the latest state.")
    args = parser.parse_args()

    if sum(bool(x) for x in [
            args.commit_range, args.since,
            args.commit != "HEAD" and (args.commit_range or args.since)]) > 1:
        # Tolerate --commit being the default while another anchor is set.
        # Only error if --commit-range AND --since are BOTH set explicitly.
        if args.commit_range and args.since:
            print("--commit-range and --since are mutually exclusive",
                  file=sys.stderr)
            return 2

    if args.avg_of_n < 1:
        print(f"--avg-of-N must be >= 1 (got {args.avg_of_n})", file=sys.stderr)
        return 2

    # W7-AUDIT-POLICY: auto-resolve the plan path from task_id prefix
    # unless --plan overrides.
    # W13-AUDIT-INFRA-W13-PLUS: W12+ task ids resolve to coord/STATUS.csv
    # — load_acceptance dispatches by source format.
    plan_path = _resolve_plan_path(args.task_id, args.plan)
    if not plan_path.exists():
        print(f"plan not found: {plan_path}", file=sys.stderr)
        return 2

    acceptance = load_acceptance(args.task_id, plan_path)
    if not acceptance:
        print(f"task {args.task_id} not found in plan {plan_path}",
              file=sys.stderr)
        return 2

    # Resolve commit anchor: --reaudit / --commit-range / --since override --commit
    if args.reaudit:
        latest = find_latest_commit_for_task(args.task_id)
        if not latest:
            print(f"--reaudit could not find a commit mentioning "
                  f"{args.task_id} in the last 50 commits", file=sys.stderr)
            return 2
        print(f"[audit] --reaudit resolved to {latest[:12]} for "
              f"{args.task_id}", file=sys.stderr)
        shas = [latest]
    elif args.commit_range:
        shas = resolve_commit_range(args.commit_range)
        if not shas:
            print(f"--commit-range {args.commit_range} resolved to no "
                  f"commits", file=sys.stderr)
            return 2
    elif args.since is not None:
        shas = resolve_commit_range(f"since:{args.since}")
        if not shas:
            print(f"--since {args.since} resolved to no commits",
                  file=sys.stderr)
            return 2
    else:
        shas = [args.commit]
    info = git_commits_info(shas)
    prompt = AUDIT_PROMPT.format(
        task_id=args.task_id,
        plan_path=plan_path,
        acceptance=acceptance,
        sha=info["sha"][:12],
        author=info["author"],
        date=info["date"],
        message=info["message"],
        diffstat=info["diffstat"][:2000],
        diff_excerpt=info["diff_excerpt"],
        file_contents=info.get("file_contents", "(none)"),
    )

    anchor_label = (
        f"range={args.commit_range}" if args.commit_range
        else f"since={args.since}" if args.since
        else f"sha={info['sha'][:12]}"
    )
    print(f"[audit] task={args.task_id} {anchor_label} "
          f"commits={len(shas)} prompt={len(prompt)} chars "
          f"avg_of_n={args.avg_of_n}", flush=True)

    # ---- run N audits (parallel if N>1) --------------------------------
    started = time.monotonic()
    if args.avg_of_n == 1:
        runs = [_dispatch_with_fallback(prompt)]
    else:
        # Cap concurrency at min(N, 5) to stay polite with MiMo rate
        # limits; 3-5 is the operator-recommended range.
        max_workers = min(args.avg_of_n, 5)
        runs = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(_dispatch_with_fallback, prompt)
                for _ in range(args.avg_of_n)
            ]
            for f in as_completed(futures):
                runs.append(f.result())
    total_latency = int((time.monotonic() - started) * 1000)

    summary = aggregate_runs(runs)

    # ---- write report --------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _resolve_outpath(args.task_id, args.avg_of_n)
    if args.avg_of_n == 1:
        body = _format_single_report(args.task_id, info, runs[0])
    else:
        body = _format_avg_report(args.task_id, info, summary)
    out_path.write_text(body, encoding="utf-8")

    # ---- log summary + exit code --------------------------------------
    if args.avg_of_n == 1:
        run = runs[0]
        if not run.success:
            print(f"[audit] failed ({total_latency}ms): {run.error}",
                  file=sys.stderr)
            return 2
        print(f"[audit] auditor: {run.auditor_used} ({run.latency_ms}ms)",
              flush=True)
        print(f"\n[audit] {args.task_id}: confidence={run.confidence:.2f}  "
              f"verdict={run.verdict}  → "
              f"{'PASS' if run.confidence >= CONFIDENCE_GATE else 'STOP'}")
        print(f"[audit] report: {out_path}")
        if run.confidence < CONFIDENCE_GATE:
            print(f"\n*** STOP — confidence {run.confidence:.2f} < gate "
                  f"{CONFIDENCE_GATE}.")
            print(f"*** Operator review required before next task.")
            return 1
        return 0

    # N > 1 — averaged path
    if summary.successful_runs == 0:
        print(f"[audit] ALL {summary.total_runs} runs failed "
              f"({total_latency}ms total)", file=sys.stderr)
        return 2
    pass_str = "PASS" if summary.passed else "STOP"
    print(f"\n[audit] {args.task_id} avg-of-{summary.total_runs}: "
          f"mean={summary.mean_confidence:.2f} "
          f"stdev={summary.stdev_confidence:.2f} "
          f"min={summary.min_confidence:.2f} max={summary.max_confidence:.2f} "
          f"pass={summary.pass_count}/{summary.total_runs} "
          f"→ {pass_str}")
    print(f"[audit] report: {out_path}")
    if not summary.passed:
        print(f"\n*** STOP — mean confidence {summary.mean_confidence:.2f} "
              f"< gate {CONFIDENCE_GATE}.")
        print(f"*** Operator review required before next task.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
