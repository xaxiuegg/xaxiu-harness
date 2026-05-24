"""20-agent operator-review panel — actually use the harness, then evaluate.

Different from audit_w_action_panel20: this reviews the WHOLE harness state
(live CLI outputs, dashboard screenshot, docs, audit history) from a
"would I use this if I were the operator?" perspective — NOT a per-commit
audit.

Each of 20 personas (10 Kimi + 10 MiMo) gets:
  - 20 evidence files from coord/reviews/operator-review-20agents/evidence/
  - One persona-specific lens
  - A directive to produce a structured review

Uses harness.engines.concrete.get_engine() directly (no xaxiu-swarm dep).
"""

from __future__ import annotations

import argparse
import concurrent.futures as _cf
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

EVIDENCE_DIR = REPO / "coord" / "reviews" / "operator-review-20agents" / "evidence"
OUTPUT_DIR = REPO / "coord" / "reviews" / "operator-review-20agents"


PERSONAS = [
    # --- Kimi (10) ---
    ("K01-fresh-agent", "kimi", "kimi-for-coding",
     "You are an AI coding agent (Claude/ChatGPT/Cursor) cloning this "
     "repo for the FIRST TIME with no prior context.  Walk through what "
     "you'd try based ONLY on docs/AGENT_QUICKSTART.md (evidence file 17). "
     "What would work, what would break, what would confuse you?"),
    ("K02-operator-cli", "kimi", "kimi-for-coding",
     "You are a CLI-literate dev/devops operator (NOT an agent).  You "
     "ran `harness today` and `harness cost-today` (evidence 01-02). "
     "Is the output actionable, or vague-pretty?  What's missing for "
     "your day-to-day operating loop?"),
    ("K03-non-technical-operator", "kimi", "kimi-for-coding",
     "You are a non-technical operator who thinks of the harness like "
     "ChatGPT/Claude Code.  Look at the dashboard screenshot description "
     "(00) + `harness today` (01).  Could you actually use this without "
     "a developer hand-holding you?  What's the next thing you'd give up on?"),
    ("K04-dashboard-ux", "kimi", "kimi-for-coding",
     "You are a UX reviewer.  The dashboard screenshot description (00) "
     "and API endpoint responses (09-14) show what the dashboard surfaces.  "
     "Three Wave 11 endpoints (/api/cost, /api/preflight-latency, "
     "/api/l5-events) returned 404.  How bad is this gap from a "
     "shipped-but-invisible perspective?"),
    ("K05-security", "kimi", "kimi-for-coding",
     "Security review: look at agent init output (15), .env handling, "
     "DPAPI fallback, the L5 escalation banner format (07).  What's "
     "an attacker's first move?  What footgun ships unfixed?"),
    ("K06-test-coverage-honesty", "kimi", "kimi-for-coding",
     "Test-coverage skeptic: the W11_E2E_SDK_PROOF.md (18) found that "
     "ALL prior W11 SDK tests were mocked — the first real call crashed.  "
     "What ELSE in the harness is likely mocked-only and has never been "
     "tested for real?  Which next 'real use' would surface the most bugs?"),
    ("K07-cost-truthfulness", "kimi", "kimi-for-coding",
     "The `harness cost-today` (evidence 02) shows '14% offload'.  "
     "But budget_status considers `swarm/kimi`, `kimi`, `mimo` as "
     "subscription.  Are the labels honest?  Will a non-technical "
     "operator misinterpret the numbers?"),
    ("K08-windows-cp1252", "kimi", "kimi-for-coding",
     "Windows console encoding review: evidence 15 caught a "
     "UnicodeEncodeError in `harness agent init` (Unicode checkmark on "
     "cp1252).  Scan the evidence files for OTHER non-ASCII output that "
     "will crash Windows consoles (em-dashes in 01, etc.).  How "
     "widespread is the issue?"),
    ("K09-onboarding-friction", "kimi", "kimi-for-coding",
     "Onboarding: an operator clones the repo.  What is the SHORTEST "
     "command chain from `git clone` to first successful dispatch?  Walk "
     "through AGENT_QUICKSTART.md (17) AND check against the actual CLI "
     "signatures.  Where does AGENT_QUICKSTART.md lie?"),
    ("K10-real-day-of-use", "kimi", "kimi-for-coding",
     "Imagine running the harness autonomously on a real project for 24h. "
     "What breaks first?  Look at observer watchdog (03), preflight (04), "
     "the dashboard (00).  Is the harness genuinely ready for unattended "
     "operation, or is it still demo-grade?"),

    # --- MiMo (10) ---
    ("M01-architecture", "mimo", "mimo-v2.5-pro",
     "Architecture review: the W11 closeout (16) claims 12/12 production "
     "rows shipped.  Reading the SDK proof (18) + agent quickstart (17), "
     "does the API surface compose cleanly?  Where's the friction between "
     "modules an agent would hit?"),
    ("M02-spec-vs-reality", "mimo", "mimo-v2.5-pro",
     "Spec drift: the wave-11-plan.md acceptance criteria included things "
     "like 'mypy --strict passes', 'harness today shows latency p50/p95', "
     "'morning email brief'.  Compare to what evidence 01-15 shows.  Which "
     "spec promises are unmet but marked shipped?"),
    ("M03-operator-decision-support", "mimo", "mimo-v2.5-pro",
     "Operator decision support: read the closeout (16) + the "
     "SESSION-*-CLOSEOUT row + STATUS.csv recent rows (19).  If you're "
     "the operator, what do you APPROVE, what do you VETO, what do you "
     "DEFER?  Be specific."),
    ("M04-agent-context-economy", "mimo", "mimo-v2.5-pro",
     "The headline W11 promise: 'agent context grows ~36 tokens/dispatch "
     "vs 1500'.  W11_E2E_SDK_PROOF.md (18) measured 142 bytes/dispatch.  "
     "Is the economy real or a measurement artifact?  What's the "
     "real-world saturation point?"),
    ("M05-test-use-blockers", "mimo", "mimo-v2.5-pro",
     "If the operator wanted to use the harness on a real project "
     "TOMORROW, what are the top-3 blockers visible in the evidence?  Be "
     "concrete: name the broken command, the missing doc, the wrong output."),
    ("M06-wave-12-priorities", "mimo", "mimo-v2.5-pro",
     "Wave 12 candidate sequencing: the closeout (16) suggests morning-"
     "email-brief, L4 alarm system, live-engine smoke, mypy --strict, "
     "dashboard polish.  Reorder by ROI per operator-hour-of-pain.  Add "
     "any missing item the evidence reveals."),
    ("M07-failure-mode-surface", "mimo", "mimo-v2.5-pro",
     "What does the operator see when things break?  Look at L5 banner "
     "demo (07), watchdog status (03), preflight (04).  Is the failure-"
     "mode UX actually usable, or operator-jargon?"),
    ("M08-real-vs-vaporware", "mimo", "mimo-v2.5-pro",
     "Which Wave 11 features genuinely shipped vs. which are skeleton "
     "code with no operator-visible surface?  Compare the closeout's "
     "12/12 (16) to what an operator actually SEES when running the "
     "harness day-to-day (01-08)."),
    ("M09-comparative-tooling", "mimo", "mimo-v2.5-pro",
     "Comparative review: vs Claude Code CLI, Cursor, Aider — what does "
     "the harness do that they don't?  What do they do better?  Where "
     "should xaxiu-harness narrow its scope to lead?"),
    ("M10-stop-or-ship", "mimo", "mimo-v2.5-pro",
     "Honest call: ship as v1.0 RC today, OR demand Wave 12 first?  "
     "Vote with a single sentence (SHIP / WAIT) + the one concrete "
     "issue from evidence that drives your vote."),
]


def _load_evidence() -> str:
    parts: list[str] = []
    for path in sorted(EVIDENCE_DIR.iterdir()):
        if path.suffix == ".png":
            parts.append(
                f"\n=== {path.name} ===\n"
                f"[binary screenshot file, {path.stat().st_size} bytes]\n"
                f"Description: Brave browser at http://localhost:8765 "
                f"showing the xaxiu-harness dashboard.  Renders Loop "
                f"(status=armed, Tick=11, Last tick 2026-05-21T00:02:35Z "
                f"— THREE DAYS STALE), Phases (all 5 armed), Active "
                f"Dispatches (2 stale entries from 2026-05-21), Status "
                f"Summary (329 shipped, 3 in_progress, 2 queued, 6 "
                f"deferred, 1 partial, 2 split, 1 merged), Wave Plan "
                f"(13 done).  NOTABLE GAPS: NO cost widget, NO L5 banner, "
                f"NO preflight latency, NO recent commit list — none of "
                f"the Wave 11 work is surfaced.\n"
            )
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            text = f"[read error: {exc}]"
        parts.append(f"\n=== {path.name} ===\n{text}")
    return "".join(parts)


def _build_prompt(persona_id: str, engine: str, lens: str,
                   evidence: str) -> str:
    return f"""You are persona **{persona_id}** ({engine}) reviewing the
xaxiu-harness post-Wave-11 state.

Your specific lens:
> {lens}

## Evidence (20 files; live captures of the actual harness state)

{evidence}

## Your task — output a STRUCTURED review

EXACTLY these sections, in this order:

### Verdict
One of: `READY` (operator can ship Wave 11 as v1.0 RC today) |
`NEEDS-WORK` (one or two specific blockers; fixable in <1 day) |
`BLOCKED` (multiple deep issues; Wave 12 required first)

### Confidence
A float in [0.0, 1.0].

### Top-3 concrete recommendations
Three actionable next-cycle items.  For each:
- One-sentence summary
- Which evidence file grounds it (e.g. "evidence 03 line 5")
- Effort estimate (S / M / L)

### Operator vote
One of: `APPROVE-AND-SHIP` | `WAIT-FOR-WAVE-12` | `ESCALATE-TO-HUMAN`

### Single quote from evidence
Pick ONE quote from the evidence (verbatim, <30 words) that best supports
your verdict.

Output as Markdown.  Be brutally honest — sugar-coating hides real bugs.
"""


def _dispatch_one(persona_id: str, engine: str, model: str, lens: str,
                   evidence: str) -> dict:
    out_path = OUTPUT_DIR / "responses" / f"{persona_id}_response.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        out_path.write_text(f"# {persona_id} engine_init_failed\n\n{exc}",
                             encoding="utf-8")
        return {"persona_id": persona_id, "engine": engine, "ok": False,
                "error": f"engine init failed: {exc}",
                "elapsed_s": time.monotonic() - started}
    prompt = _build_prompt(persona_id, engine, lens, evidence)
    try:
        resp = eng.dispatch(prompt, model, {"max_tokens": 1800})
    except Exception as exc:
        out_path.write_text(f"# {persona_id} dispatch_exception\n\n{exc}",
                             encoding="utf-8")
        return {"persona_id": persona_id, "engine": engine, "ok": False,
                "error": f"dispatch exception: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        out_path.write_text(
            f"# {persona_id} engine_returned_empty\n\n{resp.error}",
            encoding="utf-8",
        )
        return {"persona_id": persona_id, "engine": engine, "ok": False,
                "error": resp.error, "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"persona_id": persona_id, "engine": engine, "ok": True,
            "deliverable": str(out_path), "elapsed_s": elapsed,
            "tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-concurrent", type=int, default=6)
    parser.add_argument("--only", default=None,
                        help="Comma-separated persona IDs.")
    args = parser.parse_args()

    only = set(args.only.split(",")) if args.only else None
    personas = [p for p in PERSONAS if not only or p[0] in only]
    print(f"[panel] {len(personas)} personas, max_concurrent={args.max_concurrent}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    evidence = _load_evidence()
    print(f"[panel] evidence: {len(evidence)} chars across "
          f"{len(list(EVIDENCE_DIR.iterdir()))} files")

    started = time.monotonic()
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=args.max_concurrent) as pool:
        futures = {
            pool.submit(_dispatch_one, pid, engine, model, lens, evidence): pid
            for pid, engine, model, lens in personas
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            pid = r["persona_id"]
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r.get('elapsed_s', 0):.1f}s"
                     if r["ok"] else (r.get("error") or "(no error msg)")[:80])
            print(f"[panel] {flag} {pid:<32}  {extra}")
            results.append(r)

    summary_path = OUTPUT_DIR / "results_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    n_ok = sum(1 for r in results if r["ok"])
    elapsed = time.monotonic() - started
    print(f"\n[panel] {n_ok}/{len(results)} successful in {elapsed:.0f}s")
    print(f"[panel] responses: {OUTPUT_DIR / 'responses'}")
    print(f"[panel] summary:   {summary_path}")
    return 0 if n_ok >= len(results) * 0.75 else 1


if __name__ == "__main__":
    sys.exit(main())
