"""v1.0.0 release-gate panel: APPROVE/BLOCK the v1.0.0 tag.

Friday re-panel per coord/CURRENT_PLAN.md "Single most important action
(live)". Each of 3 engines (Kimi + DeepSeek + MiMo) gets the same source
pack and answers ONE binary question: given what shipped this week
against the Round 2 forward plan, do you APPROVE tagging `v1.0.0`
final or BLOCK with specific reason?

Decision rule (per operator 2026-05-25):
- >=2/3 APPROVE -> tag v1.0.0 final.
- <2/3 APPROVE -> list per-engine blockers in FINAL_VERDICT.md, fix,
  re-fire.
- MiMo has a history of failing on strategic synthesis (Round 2 verdict);
  Kimi + DeepSeek alone is sufficient. Proceed on 2/2 APPROVE if MiMo
  fails, OR on 1/1 + DeepSeek complete.

3 dispatches, max_tokens=8000 each. Expected cost: $0 (subscription).
"""
from __future__ import annotations

import concurrent.futures as _cf
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO / "coord" / "reviews" / "v1-release-gate"
OUT_DIR.mkdir(parents=True, exist_ok=True)


W13_ROWS_THIS_WEEK = [
    "W13-FUTURE-MARKER-AUDIT",
    "W13-INSTALL-VERIFY",
    "W13-AUDIT-JSONL",
    "W13-SDK-REVIEW-AND-CAPABILITIES",
    "W13-DOC-SDK-COVERAGE",
    "W13-HARNESS-PLAN-VERB",
    "W13-CLAUDEMD-INVOCATION",
    "W13-FRESH-CLONE-BOOTSTRAP",
    "W13-PYTHON-M-HARNESS-FORM",
    "W13-MORNING-BRIEF-CONTEXT-BUG",
    "W13-AUDIT-INFRA-W12-PLUS",
]


def _read_status_rows(ids: list[str]) -> str:
    """Pull the requested rows out of STATUS.csv as a Markdown block."""
    path = REPO / "coord" / "STATUS.csv"
    if not path.exists():
        return "(STATUS.csv not found)"
    wanted = set(ids)
    found: dict[str, dict] = {}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            rid = (row.get("ID") or "").strip()
            if rid in wanted:
                found[rid] = row
    lines: list[str] = []
    for rid in ids:
        r = found.get(rid)
        if r is None:
            lines.append(f"### {rid}\n\n(NOT FOUND in STATUS.csv)\n")
            continue
        lines.append(
            f"### {rid}\n\n"
            f"- **Category**: {r.get('Category', '')}\n"
            f"- **Title**: {r.get('Title', '')}\n"
            f"- **Status**: {r.get('Status', '')}\n"
            f"- **Owner**: {r.get('Owner', '')}\n"
            f"- **Effort**: {r.get('Effort', '')}\n"
            f"- **Updated**: {r.get('Updated', '')}\n\n"
            f"**Notes**: {r.get('Notes', '')}\n"
        )
    return "\n".join(lines)


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, cwd=REPO, timeout=60,
        )
        return r.stdout + (r.stderr if r.returncode != 0 else "")
    except Exception as exc:
        return f"(failed: {exc})"


def _load_source() -> str:
    """Build the source pack shown to all 3 engines."""
    parts: list[str] = []

    # 1. Current strategic plan (post-fix-Friday)
    plan = REPO / "coord" / "CURRENT_PLAN.md"
    if plan.exists():
        parts.append(
            f"=== coord/CURRENT_PLAN.md ===\n\n"
            f"{plan.read_text(encoding='utf-8', errors='replace')}"
        )

    # 2. Round 2 final verdict (the bar this panel re-tests against)
    verdict = (REPO / "coord" / "reviews"
               / "strategic-planning-panel15-final-verdict"
               / "FINAL_VERDICT.md")
    if verdict.exists():
        parts.append(
            f"\n\n=== Round 2 FINAL_VERDICT.md ===\n\n"
            f"{verdict.read_text(encoding='utf-8', errors='replace')}"
        )

    # 3. The W13 rows that shipped this week (the actual evidence)
    parts.append(
        "\n\n=== W13 rows shipped this week (from coord/STATUS.csv) ===\n\n"
        + _read_status_rows(W13_ROWS_THIS_WEEK)
    )

    # 4. Live capability snapshot
    caps = _run([sys.executable, "-m", "harness", "capabilities",
                 "--format", "json"])
    parts.append(
        "\n\n=== Live capability snapshot (python -m harness capabilities --format json) ===\n\n"
        "```json\n" + caps.strip() + "\n```\n"
    )

    # 5. Week's git log
    log = _run(["git", "log", "--since=2026-05-18", "--oneline"])
    parts.append(
        "\n\n=== Git log this week (--since=2026-05-18) ===\n\n"
        "```\n" + log.strip() + "\n```\n"
    )

    # 6. Bootstrap-validation note (operator-specified, load-bearing)
    parts.append(
        "\n\n=== Bootstrap one-liner validation ===\n\n"
        "The session-resume one-liner —\n\n"
        "    pip install -e . --quiet && python -m harness today && python -m harness plan show\n\n"
        "— was validated end-to-end by BOTH a fresh-worktree sub-agent AND "
        "a real fresh session (iteration-3 of the orientation fix that landed "
        "as W13-FRESH-CLONE-BOOTSTRAP + W13-CLAUDEMD-INVOCATION + "
        "W13-PYTHON-M-HARNESS-FORM). This is load-bearing evidence that the "
        "install path actually works for v1.0.0 — a fresh agent on a fresh "
        "clone can bootstrap and self-orient without operator help.\n"
    )

    return "".join(parts)


PROMPT = """You are a senior engineer rendering the FINAL release-gate
verdict on `xaxiu-harness v1.0.0`.

## Project framing

xaxiu-harness is an internal-tool (Horizon C, NOT commercial product),
solo-operator multi-engine LLM dispatch + observability framework. Per the
operator directive 2026-05-25, the project optimizes for
visible/overridable/auditable behavior over feature breadth. The Round 2
strategic planning panel (15 personas, then 3-engine final verdict)
produced a forward plan with a SHIP list, a DROP list, and 6 dissents.
This week (Mon-Fri, 2026-05-18..2026-05-25), Week 1 of that plan shipped.

You are being asked NOW whether the system is ready to be tagged
`v1.0.0` final.

## Source pack

{source}

---

## Your task

Render ONE binary verdict at the top of your response:

**VERDICT: APPROVE** — ship v1.0.0 final as-is.
**VERDICT: BLOCK** — there is a specific, named blocker that must land
                     before v1.0.0 tag.

Then in 400-1200 words, answer:

1. **Did Week 1 actually ship?** Go through each row in CURRENT_PLAN.md's
   "Shipped this week" table. For each, does the STATUS.csv Notes column
   substantiate the "shipped" claim? Flag any rows where the description
   sounds bigger than what the notes actually demonstrate.

2. **Are the universal panel picks (W13-INSTALL-VERIFY +
   W13-AUDIT-JSONL) load-bearing?** These were the Round 2 universal #1
   and #2. Look at the actual implementation evidence (test counts, what
   the secret-redaction patterns cover, what the install-verify gate
   tests). Is this enough to trust auto-defaults going forward?

3. **Is the install path actually trustworthy?** The bootstrap one-liner
   was validated by sub-agent AND fresh session per the source pack. Do
   you trust this as v1.0.0 quality, or would you want more evidence?

4. **What does the live capability snapshot tell you?** The
   `harness capabilities --format json` output is in the source pack.
   Does it match what CURRENT_PLAN.md claims shipped? Any gaps?

5. **Did the dissents from Round 2 get resolved correctly?** Round 2
   left some open questions (auto-default shape, max_tokens heuristic,
   audit-trail before auto-defaults). The week's work answered them
   implicitly via what shipped. Are you comfortable with how each was
   resolved?

6. **Single blocker (if BLOCK):** name the ONE concrete thing that must
   land before v1.0.0. Be specific — a file, a feature, a test, a row.

7. **Confidence (0.0-1.0):** how confident are you in this verdict?

## Output rules

- Start with `VERDICT: APPROVE` or `VERDICT: BLOCK` on its own line.
- Be brutally honest. The operator wants a real gate, not a rubber stamp.
- Don't sandbag. Don't fence-sit. Pick a side.
- Cite specific row IDs (W13-XXX) when you reference what shipped.
- If you BLOCK, the blocker must be concrete enough that fixing it is a
  named row of work, not a vague concern.
- Output Markdown.
"""


def _dispatch(engine: str, model: str, source: str) -> dict:
    started = time.monotonic()
    out_path = OUT_DIR / f"{engine}_verdict.md"
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        out_path.write_text(f"# {engine} engine_init_failed\n\n{exc}",
                             encoding="utf-8")
        return {"engine": engine, "ok": False,
                "verdict": "ERROR",
                "error": str(exc),
                "elapsed_s": time.monotonic() - started}
    prompt = PROMPT.format(source=source)
    try:
        resp = eng.dispatch(prompt, model, {"max_tokens": 8000})
    except Exception as exc:
        out_path.write_text(
            f"# {engine} dispatch_exception\n\n{exc}",
            encoding="utf-8",
        )
        return {"engine": engine, "ok": False,
                "verdict": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        out_path.write_text(
            f"# {engine} engine_returned_empty\n\n{resp.error}",
            encoding="utf-8",
        )
        return {"engine": engine, "ok": False,
                "verdict": "ERROR",
                "error": resp.error or "(empty)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    # Parse the leading VERDICT line.
    verdict = "UNKNOWN"
    for line in (resp.text or "").splitlines()[:10]:
        L = line.strip().upper()
        if "VERDICT: APPROVE" in L or L == "APPROVE":
            verdict = "APPROVE"
            break
        if "VERDICT: BLOCK" in L or L == "BLOCK":
            verdict = "BLOCK"
            break
    return {"engine": engine, "ok": True, "verdict": verdict,
            "elapsed_s": elapsed, "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out, "cost_usd": resp.cost_usd}


def _synth(results: list[dict], source_chars: int) -> str:
    approves = [r for r in results if r["verdict"] == "APPROVE"]
    blocks = [r for r in results if r["verdict"] == "BLOCK"]
    errors = [r for r in results if r["verdict"] in ("ERROR", "UNKNOWN")]

    if len(approves) >= 2:
        decision = "APPROVE"
    elif len(approves) == 1 and len(blocks) == 0 and len(errors) <= 2:
        decision = "APPROVE (1/1 + degraded; MiMo strategic failure precedent)"
    elif len(blocks) >= 1:
        decision = "BLOCK"
    else:
        decision = "INSUFFICIENT-SIGNAL"

    lines = [
        "# v1.0.0 release-gate panel — FINAL VERDICT",
        "",
        f"**Decision**: {decision}",
        f"**Vote**: {len(approves)} APPROVE / {len(blocks)} BLOCK / "
        f"{len(errors)} ERROR-or-UNKNOWN",
        f"**Source pack size**: {source_chars} chars",
        "",
        "## Per-engine verdicts",
        "",
        "| Engine | Verdict | Elapsed | In | Out | Cost |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['engine']} | **{r['verdict']}** | "
            f"{r.get('elapsed_s', 0):.1f}s | "
            f"{r.get('tokens_in', '-')} | {r.get('tokens_out', '-')} | "
            f"${r.get('cost_usd', 0):.4f} |"
        )
    lines.append("")
    lines.append("## Engine-level detail")
    lines.append("")
    for r in results:
        lines.append(f"### {r['engine']}")
        lines.append("")
        if r["ok"]:
            lines.append(f"See [`{r['engine']}_verdict.md`]"
                          f"({r['engine']}_verdict.md) for the full response.")
        else:
            lines.append(f"FAILED: {r.get('error', '?')}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    source = _load_source()
    print(f"[v1-gate] source: {len(source)} chars")
    print(f"[v1-gate] dispatching Kimi + DeepSeek + MiMo in parallel...")

    engines = [
        ("kimi", "kimi-for-coding"),
        ("deepseek", "deepseek-v4-flash"),
        ("mimo", "mimo-v2.5-pro"),
    ]
    started = time.monotonic()
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_dispatch, eng, mdl, source): eng
            for eng, mdl in engines
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = r["verdict"] if r["ok"] else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"in/out={r.get('tokens_in', 0)}/{r.get('tokens_out', 0)}"
                     if r["ok"]
                     else (r.get("error") or "")[:80])
            print(f"[v1-gate] {flag:<10} {r['engine']:<10} {extra}")
            results.append(r)
    elapsed = time.monotonic() - started
    print(f"\n[v1-gate] complete in {elapsed:.0f}s")

    final = _synth(results, len(source))
    (OUT_DIR / "FINAL_VERDICT.md").write_text(final, encoding="utf-8")
    print(f"[v1-gate] wrote {OUT_DIR / 'FINAL_VERDICT.md'}")
    print()
    print(final)
    return 0


if __name__ == "__main__":
    sys.exit(main())
