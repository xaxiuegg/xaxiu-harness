"""20-agent operator-review panel Round 2: did Wave 12-A fix the findings?

Same 20 personas as Round 1, but each is now asked the SAME question:
"Round 1 voted WAIT-FOR-WAVE-12 for 3 universal blockers (Unicode crash,
dashboard 404s, watchdog-jargon).  Wave 12-A shipped commit 60ecfcf
claiming to fix them.  Does the Round-2 evidence prove the fixes work?
Does your verdict shift?"

Crucially each persona gets BOTH the Round 1 synthesis (so they remember
what they flagged) AND the Round 2 evidence (so they can verify).
"""

from __future__ import annotations

import argparse
import concurrent.futures as _cf
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

EVIDENCE_DIR = REPO / "coord" / "reviews" / "operator-review-20agents-round2" / "evidence"
OUTPUT_DIR = REPO / "coord" / "reviews" / "operator-review-20agents-round2"


# Same persona lineup as Round 1, but the prompt is now "did the fixes work?".
PERSONAS = [
    ("K01-fresh-agent", "kimi", "kimi-for-coding"),
    ("K02-operator-cli", "kimi", "kimi-for-coding"),
    ("K03-non-technical-operator", "kimi", "kimi-for-coding"),
    ("K04-dashboard-ux", "kimi", "kimi-for-coding"),
    ("K05-security", "kimi", "kimi-for-coding"),
    ("K06-test-coverage-honesty", "kimi", "kimi-for-coding"),
    ("K07-cost-truthfulness", "kimi", "kimi-for-coding"),
    ("K08-windows-cp1252", "kimi", "kimi-for-coding"),
    ("K09-onboarding-friction", "kimi", "kimi-for-coding"),
    ("K10-real-day-of-use", "kimi", "kimi-for-coding"),
    ("M01-architecture", "mimo", "mimo-v2.5-pro"),
    ("M02-spec-vs-reality", "mimo", "mimo-v2.5-pro"),
    ("M03-operator-decision-support", "mimo", "mimo-v2.5-pro"),
    ("M04-agent-context-economy", "mimo", "mimo-v2.5-pro"),
    ("M05-test-use-blockers", "mimo", "mimo-v2.5-pro"),
    ("M06-wave-12-priorities", "mimo", "mimo-v2.5-pro"),
    ("M07-failure-mode-surface", "mimo", "mimo-v2.5-pro"),
    ("M08-real-vs-vaporware", "mimo", "mimo-v2.5-pro"),
    ("M09-comparative-tooling", "mimo", "mimo-v2.5-pro"),
    ("M10-stop-or-ship", "mimo", "mimo-v2.5-pro"),
]


def _load_evidence() -> str:
    parts: list[str] = []
    for path in sorted(EVIDENCE_DIR.iterdir()):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            text = f"[read error: {exc}]"
        parts.append(f"\n=== {path.name} ===\n{text}")
    return "".join(parts)


def _build_prompt(persona_id: str, engine: str, evidence: str) -> str:
    return f"""# Round 2 operator-review panel — {persona_id} ({engine})

You are persona **{persona_id}** ({engine}) — same persona that voted
in Round 1.  The Round 1 synthesis (in the evidence below as
`22_round1_synthesis.md`) found 3 universal blockers:

1. Windows cp1252 Unicode crash (19/19 personas flagged)
2. Dashboard 404s on /api/cost, /api/preflight-latency, /api/l5-events,
   /api/loop (16/19 personas flagged)
3. Watchdog jargon / loop staleness invisible (8/19 personas flagged)

Wave 12-A shipped commit `60ecfcf` claiming to fix all three.  Round 2
evidence (CLI outputs + dashboard API responses) was just captured.

## Round 2 evidence (17 files; live captures POST-fix)

{evidence}

## Your task: did the fixes actually work?

Output EXACTLY these sections:

### Verdict shift
One of:
- `READY` (Round-1 verdict was NEEDS-WORK/BLOCKED; now satisfied — fixes proven by evidence)
- `STILL-NEEDS-WORK` (some fixes landed, others didn't or new gaps emerged)
- `WORSE` (something regressed)

### Confidence
A float in [0.0, 1.0].

### Per-blocker assessment
For each Round-1 blocker, state PROVEN-FIXED / PARTIAL / NOT-FIXED + the
specific evidence line that grounds your call:

1. Unicode crash (preflight + --help + agent init):
2. Dashboard 404s (/api/cost + /api/preflight-latency + /api/l5-events + /api/loop):
3. Watchdog jargon / loop staleness:

### New blockers (if any)
Things that surfaced this round that weren't in Round 1.

### Operator vote
One of: `APPROVE-AND-SHIP` | `WAIT-FOR-WAVE-12-B` | `ESCALATE-TO-HUMAN`

### Single grounding quote
ONE quote from Round 2 evidence (verbatim, <30 words) that drives your
verdict shift.

Output as Markdown.  Be brutally honest.
"""


def _dispatch_one(persona_id: str, engine: str, model: str,
                   evidence: str) -> dict:
    out_path = OUTPUT_DIR / "responses" / f"{persona_id}_response.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        out_path.write_text(f"# {persona_id} engine_init_failed\n\n{exc}",
                             encoding="utf-8")
        return {"persona_id": persona_id, "ok": False,
                "error": f"engine init failed: {exc}",
                "elapsed_s": time.monotonic() - started}
    prompt = _build_prompt(persona_id, engine, evidence)
    try:
        resp = eng.dispatch(prompt, model, {"max_tokens": 1500})
    except Exception as exc:
        out_path.write_text(f"# {persona_id} dispatch_exception\n\n{exc}",
                             encoding="utf-8")
        return {"persona_id": persona_id, "ok": False,
                "error": f"dispatch: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        out_path.write_text(
            f"# {persona_id} engine_returned_empty\n\n{resp.error}",
            encoding="utf-8",
        )
        return {"persona_id": persona_id, "ok": False,
                "error": resp.error or "(empty response)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"persona_id": persona_id, "ok": True,
            "deliverable": str(out_path), "elapsed_s": elapsed,
            "tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-concurrent", type=int, default=8)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    only = set(args.only.split(",")) if args.only else None
    personas = [p for p in PERSONAS if not only or p[0] in only]
    print(f"[panel] {len(personas)} personas, "
          f"max_concurrent={args.max_concurrent}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    evidence = _load_evidence()
    print(f"[panel] evidence: {len(evidence)} chars across "
          f"{len(list(EVIDENCE_DIR.iterdir()))} files")

    started = time.monotonic()
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=args.max_concurrent) as pool:
        futures = {
            pool.submit(_dispatch_one, pid, engine, model, evidence): pid
            for pid, engine, model in personas
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            pid = r["persona_id"]
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r.get('elapsed_s', 0):.1f}s"
                     if r["ok"]
                     else (r.get("error") or "(no error msg)")[:80])
            print(f"[panel] {flag} {pid:<32}  {extra}")
            results.append(r)

    summary_path = OUTPUT_DIR / "results_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    n_ok = sum(1 for r in results if r["ok"])
    elapsed = time.monotonic() - started
    print(f"\n[panel] {n_ok}/{len(results)} successful in {elapsed:.0f}s")
    return 0 if n_ok >= len(results) * 0.75 else 1


if __name__ == "__main__":
    sys.exit(main())
