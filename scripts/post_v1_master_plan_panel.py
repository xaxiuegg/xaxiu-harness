"""Post-v1.0.0 master-plan panel.

Operator directive 2026-05-25 (after v1.0.0 shipped + the engine-failure-
visibility layer landed):

    "create a panel with 5 agents of each engine and ask for their stance
     then create a master plan for us to run"

Original intent was 5 personas x 3 engines = 15 agents.  Kimi is out
(account terminated, W14-KIMI-AUTH-RESTORE), so the realized panel is
5 personas x 2 engines = 10 agents (5 DeepSeek + 5 MiMo).

Each persona gets a different framing that forces a different lens:

  1. **Architect**       — structural decisions for the next 3-6 months
  2. **Operator-UX**     — what hurts the solo operator most day-to-day
  3. **Performance**     — where will we be slow / brittle / expensive
  4. **Security/Audit**  — next audit-trail / blast-radius / secret-handling gap
  5. **Velocity**        — what unblocks the most future work the fastest

Each lens is asked to render a stance + propose top 3 things to ship next +
identify the single most important action.  The synthesis aggregates by
convergence + flags dissent.

10 dispatches, max_tokens=8000 each.  Expected cost: ~$0 (subscription /
tp- token plan).

Output: coord/reviews/post-v1-master-plan/{deepseek,mimo}_<persona>.md +
MASTER_PLAN.md synthesis.
"""
from __future__ import annotations

import concurrent.futures as _cf
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO / "coord" / "reviews" / "post-v1-master-plan"
OUT_DIR.mkdir(parents=True, exist_ok=True)


PERSONAS: list[tuple[str, str]] = [
    ("architect",
     "**Architect** — You are a senior software architect with deep "
     "experience in solo-operator dev tools.  Your lens is STRUCTURAL "
     "decisions for the next 3-6 months: what abstractions are load-"
     "bearing, what's about to bend under its own weight, what should "
     "be solidified vs torn out.  You do NOT recommend new features "
     "unless they're structural.  You DO recommend refactors, "
     "abstraction-collapsing, schema-versioning, and breaking-change "
     "windows."),
    ("operator-ux",
     "**Operator-UX** — You are a UX researcher who has watched 50 "
     "solo developers struggle with internal dev tools.  Your lens is "
     "what HURTS the operator day-to-day: friction, surprise, "
     "invisibility, recovery cost.  You weight high-frequency papercuts "
     "above rare-but-severe failures, and you weight DISCOVERABILITY "
     "above raw capability.  You recommend things that make the tool "
     "feel responsive and trustworthy."),
    ("performance",
     "**Performance** — You are a systems engineer with budget "
     "instincts.  Your lens is COST, LATENCY, and RELIABILITY: where "
     "is this tool slow, where does it waste tokens, where does it "
     "make the operator wait, where does it fall over silently.  You "
     "recommend cache wins, dispatch-tier policy, parallel-execution "
     "gating, and timeout/retry tuning.  Numbers in your reasoning "
     "trump intuition."),
    ("security-audit",
     "**Security/Audit** — You are a security engineer who has done "
     "300 IR engagements.  Your lens is BLAST-RADIUS and AUDITABILITY: "
     "what happens when a key leaks, a vendor terminates, a packet "
     "contains PII, an audit subpoena hits.  You recommend redaction, "
     "audit-trail completeness, integrity verification, and rotation "
     "discipline.  Today's Kimi termination is your kind of incident; "
     "what should we have had in place that we didn't?"),
    ("velocity",
     "**Velocity** — You are a tech lead who optimizes for SHIPPING "
     "THE NEXT THING FASTER.  Your lens is UNBLOCKING: what one piece "
     "of infrastructure, once it exists, would let us ship 5 future "
     "things at half the cost?  You recommend force-multipliers, "
     "templating, code-gen, and convention-over-configuration moves.  "
     "You explicitly de-prioritize maintenance and polish in favor of "
     "compound leverage."),
]


def _read_status_rows(ids: list[str]) -> str:
    """Pull specific rows out of STATUS.csv as a Markdown block."""
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
        notes = (r.get("Notes") or "")
        # Truncate any single Notes value at ~1800 chars to keep the
        # source pack reasonable.
        if len(notes) > 1800:
            notes = notes[:1800] + " [...truncated...]"
        lines.append(
            f"### {rid}\n\n"
            f"- **Category**: {r.get('Category', '')}\n"
            f"- **Title**: {r.get('Title', '')}\n"
            f"- **Status**: {r.get('Status', '')}\n"
            f"- **Notes**: {notes}\n"
        )
    return "\n".join(lines)


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, cwd=REPO, timeout=60,
        )
        return (r.stdout or "") + (r.stderr if r.returncode != 0 else "")
    except Exception as exc:
        return f"(failed: {exc})"


def _load_source() -> str:
    """Build the source pack — same for every persona/engine."""
    parts: list[str] = []

    parts.append(
        "=== Operator's question ===\n\n"
        "v1.0.0 just shipped (2/3 release-gate APPROVE, Kimi engine "
        "auth-out + tracked separately as L5).  The new engine-failure-"
        "visibility layer just landed (live probes + categorization + "
        "harness engines failures CLI).  What is the master plan we "
        "should run NEXT?\n\n"
        "Operator framing (durable across the session):\n"
        "- Horizon C internal tool, NOT commercial product\n"
        "- Solo operator (operator is non-technical for some classes of work)\n"
        "- Optimize for visible/overridable/auditable\n"
        "- Drop multi-user / plugin-marketplace / VPS / best-of-N\n"
        "- Full-dev-authority during execution; only L5 escalates\n"
    )

    plan = REPO / "coord" / "CURRENT_PLAN.md"
    if plan.exists():
        parts.append(
            f"\n\n=== coord/CURRENT_PLAN.md (current strategic plan) ===\n\n"
            f"{plan.read_text(encoding='utf-8', errors='replace')}"
        )

    release = REPO / "coord" / "releases" / "v1.0.0.md"
    if release.exists():
        parts.append(
            f"\n\n=== coord/releases/v1.0.0.md (what v1.0.0 actually is) ===\n\n"
            f"{release.read_text(encoding='utf-8', errors='replace')}"
        )

    verdict = (REPO / "coord" / "reviews" / "v1-release-gate"
               / "FINAL_VERDICT.md")
    if verdict.exists():
        parts.append(
            f"\n\n=== Friday release-gate FINAL_VERDICT.md ===\n\n"
            f"{verdict.read_text(encoding='utf-8', errors='replace')}"
        )

    # The fresh W13 + W14 rows that didn't exist for the prior panel
    parts.append(
        "\n\n=== Today's fresh STATUS.csv rows (post-v1.0.0) ===\n\n"
        + _read_status_rows([
            "W13-MORNING-BRIEF-CONTEXT-BUG",
            "W13-AUDIT-INFRA-W12-PLUS",
            "W13-V1-RELEASE-GATE",
            "W13-ENGINE-FAILURE-VISIBILITY",
            "W14-KIMI-AUTH-RESTORE",
        ])
    )

    # Live capability snapshot
    caps = _run([sys.executable, "-m", "harness", "capabilities",
                 "--format", "json"])
    parts.append(
        "\n\n=== Live capability snapshot (post-v1.0.0) ===\n\n"
        "```json\n" + caps.strip() + "\n```\n"
    )

    # Live engine health (the new live probe)
    health = _run([sys.executable, "-m", "harness", "engines", "--health"])
    parts.append(
        "\n\n=== Live engine health (W13-ENGINE-FAILURE-VISIBILITY output) ===\n\n"
        "```\n" + health.strip() + "\n```\n"
    )

    # Engine failure summary for the last 7 days
    failures = _run([sys.executable, "-m", "harness", "engines",
                     "failures", "--since-hours", "168"])
    parts.append(
        "\n\n=== Engine failure summary (last 168h) ===\n\n"
        "```\n" + failures.strip()[:3000] + "\n```\n"
    )

    return "".join(parts)


PROMPT_TEMPLATE = """You are part of a multi-persona panel rendering the
**post-v1.0.0 master plan** for xaxiu-harness.  v1.0.0 just shipped
(today, 2026-05-25).  Your job is to render YOUR LENS on what should
come next.

## Your persona

{persona_intro}

You are NOT a generalist this round.  Render advice ONLY through your
lens.  If a row doesn't fit your lens, skip it.

## Source pack (same for every persona)

{source}

---

## Your task

Write a Markdown response with these EXACT sections.  Be specific —
cite W*-* row IDs, file paths, and concrete next moves.  No hedging.

### Stance summary (3-5 sentences)

What is the headline observation YOUR LENS reveals about the current
state of xaxiu-harness?  What's the one thing you wish v1.0.0 had
included that it didn't?  What's the most important property to
preserve / strengthen as we move forward?

### Top 3 rows to ship next (ranked)

For each, give:
- **Row ID** (invent a new ID if needed, format `W14-<SOMETHING>` or
  `W15-<SOMETHING>` — pick whichever wave makes sense)
- **Title** (one line)
- **Estimated effort** (S/M/L)
- **Why this row, by YOUR lens** (2-4 sentences — include WHAT property
  it strengthens and what concrete pain it removes)
- **Acceptance criteria** (3-5 bullets — what does "done" look like)

### Rows you'd DROP from CURRENT_PLAN.md's Week 2/Week 3 sections

For each, give:
- **Row** (cite the existing row in CURRENT_PLAN.md)
- **Why drop** (1-2 sentences — does it fail YOUR lens's prioritization?)

If your lens has nothing to drop, write "(none — current plan respects
this lens)".

### Single most important action this week

ONE sentence.  Through YOUR lens, the single highest-leverage move.

### Confidence in your own recommendation (0.0-1.0)

One number + one sentence explaining what would make you less or more
confident.

### What this lens systematically MISSES

One sentence acknowledging the blindspot of YOUR lens — what other
perspectives should review your picks before they're shipped.

---

Output Markdown only.  No preamble, no apology, no "as an AI".  Lean
into the persona.  Specifics over abstractions.  If you find yourself
writing "should consider" or "might want to" — stop and pick a side.
"""


def _dispatch(engine: str, model: str, persona_id: str,
              persona_intro: str, source: str) -> dict:
    started = time.monotonic()
    out_path = OUT_DIR / f"{engine}_{persona_id}.md"
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        out_path.write_text(
            f"# {engine}/{persona_id} engine_init_failed\n\n{exc}",
            encoding="utf-8",
        )
        return {"engine": engine, "persona": persona_id, "ok": False,
                "error": str(exc),
                "elapsed_s": time.monotonic() - started}
    prompt = PROMPT_TEMPLATE.format(
        persona_intro=persona_intro, source=source,
    )
    try:
        resp = eng.dispatch(prompt, model, {"max_tokens": 8000})
    except Exception as exc:
        out_path.write_text(
            f"# {engine}/{persona_id} dispatch_exception\n\n{exc}",
            encoding="utf-8",
        )
        return {"engine": engine, "persona": persona_id, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        out_path.write_text(
            f"# {engine}/{persona_id} engine_returned_empty\n\n{resp.error}",
            encoding="utf-8",
        )
        return {"engine": engine, "persona": persona_id, "ok": False,
                "error": resp.error or "(empty)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"engine": engine, "persona": persona_id, "ok": True,
            "elapsed_s": elapsed, "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out, "cost_usd": resp.cost_usd}


def _retry_one(engine: str, model: str, persona_id: str,
                persona_intro: str, source: str, attempts: int = 2) -> dict:
    """Retry a failed dispatch up to ``attempts`` times.  Used for MiMo's
    known transient RemoteProtocolError pattern (W13-ENGINE-RETRY-RESILIENT).
    """
    last = None
    for n in range(attempts):
        r = _dispatch(engine, model, persona_id, persona_intro, source)
        if r["ok"]:
            return r
        last = r
        time.sleep(0.5)
    return last or {"engine": engine, "persona": persona_id, "ok": False,
                    "error": "all retries exhausted"}


def main() -> int:
    source = _load_source()
    print(f"[master-plan] source: {len(source)} chars")
    print(f"[master-plan] firing 10 dispatches "
          f"(5 personas x 2 engines)...")

    # Engine x persona matrix — kimi excluded (terminated).
    engines = [
        ("deepseek", "deepseek-v4-flash"),
        ("mimo", "mimo-v2.5-pro"),
    ]
    matrix: list[tuple[str, str, str, str]] = []
    for eng, model in engines:
        for pid, intro in PERSONAS:
            matrix.append((eng, model, pid, intro))

    started = time.monotonic()
    results: list[dict] = []
    # MiMo has a known parallel-dispatch flakiness pattern; cap workers
    # at 4 so we don't hit RemoteProtocolErrors as often.  4 workers
    # against 10 tasks gives ~3 batches.
    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_retry_one, eng, mdl, pid, intro, source): (eng, pid)
            for eng, mdl, pid, intro in matrix
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"out={r.get('tokens_out', '-')}"
                     if r["ok"]
                     else (r.get("error") or "")[:80])
            print(f"[master-plan] {flag:<5} {r['engine']:<10} "
                   f"{r['persona']:<15} {extra}")
            results.append(r)
    elapsed = time.monotonic() - started
    ok_count = sum(1 for r in results if r["ok"])
    print(f"\n[master-plan] {ok_count}/{len(results)} complete "
          f"in {elapsed:.0f}s")

    # Write a thin index — the actual synthesis happens in a separate
    # pass (we read all 10 responses + ask Claude to synthesize).  The
    # operator will run the synthesis step from chat.
    index_lines = [
        "# Post-v1.0.0 master-plan panel — INDEX",
        "",
        f"**Fired**: 2026-05-25 (after v1.0.0 tag + W13-ENGINE-FAILURE-VISIBILITY)",
        f"**Result**: {ok_count}/{len(results)} dispatches complete",
        f"**Source pack**: {len(source)} chars",
        "",
        "## Per-dispatch results",
        "",
        "| Engine | Persona | Result | Elapsed | Out tokens |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda x: (x['engine'], x['persona'])):
        result_text = "OK" if r["ok"] else f"FAIL ({(r.get('error') or '')[:50]})"
        if r["ok"]:
            link = f"[{r['engine']}_{r['persona']}.md]({r['engine']}_{r['persona']}.md)"
        else:
            link = f"`{r['engine']}_{r['persona']}.md`"
        index_lines.append(
            f"| {link} | {r['persona']} | {result_text} | "
            f"{r.get('elapsed_s', 0):.1f}s | {r.get('tokens_out', '-')} |"
        )
    index_lines.append("")
    index_lines.append("Next step: synthesize across all 10 (or however "
                        "many succeeded) responses into MASTER_PLAN.md")
    (OUT_DIR / "INDEX.md").write_text("\n".join(index_lines),
                                       encoding="utf-8")
    print(f"[master-plan] wrote {OUT_DIR / 'INDEX.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
