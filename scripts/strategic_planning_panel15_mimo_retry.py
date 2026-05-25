"""Retry the 5 MiMo personas with a smaller source pack.

Main panel run had all 5 MiMo dispatches fail with 'internal' error,
likely because the 96KB source pack exceeded MiMo's effective context
window.  This retry sends only the 2 most-relevant docs (bloat audit +
horizon-c plan), ~25KB total.
"""
from __future__ import annotations

import concurrent.futures as _cf
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO / "coord" / "reviews" / "strategic-planning-panel15"

# Smaller pack — just the two strategic docs
SMALL_SOURCE_FILES = [
    "coord/reviews/bloat-audit-2026-05-25.md",
    "coord/reviews/horizon-c-internal-tool-plan.md",
]


def _load_small_pack() -> str:
    parts = []
    for rel in SMALL_SOURCE_FILES:
        path = REPO / rel
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"\n\n=== FILE: {rel} ===\n\n{text}")
    return "".join(parts)


# Same personas as the main panel
PERSONAS = [
    ("M1-risk-and-safety",
     """Your lens: risk + safety review of the Tier 1-3 shifts AND the
Wave 13 remaining rows.  For each proposed shift + each backlog row,
identify: (a) the worst-case silent failure, (b) the detection-latency,
(c) the blast radius, (d) the rollback cost.  Then RANK the proposed
work by risk-adjusted ROI."""),
    ("M2-sequencing-strategy",
     """Your lens: SEQUENCING.  Given 1-3h operator evenings + 5h
weekends, what's the OPTIMAL order to ship the remaining work?  Wave 13
has 6 unshipped rows; the bloat audit proposes Tier 1-3 shifts (8 rows);
Horizon C plan has Wave 14-17 (15+ rows).  Order all by sequence, show
the operator EXACTLY which row to ship Monday, Tuesday, etc., for the
next 2 weeks.  Include STOP-and-re-evaluate decision points."""),
    ("M3-hallucination-deep-dive",
     """Your lens: hallucination vectors not yet identified.  Think
beyond the 6 vectors in the bloat audit.  Consider: SDK signature
changes breaking old caller patterns, CLI verb deprecation, config-key
drift between YAML schemas, engine-model coupling when vendor renames a
model, STATUS.csv schema migrations, observer state migrations, dispatch
cache binary compat across harness versions.  For each NEW vector,
propose ONE specific mitigation with effort estimate."""),
    ("M4-roi-sequence-rigor",
     """Your lens: rigorous ROI.  For every proposed row + shift,
estimate operator-hours-saved over 6 months / implementation-hours.
Rank ALL proposed work (Tier 1-3 + Wave 13 + cross-engine-review-flagged
rows + Horizon C).  Identify TOP 5 highest-ROI moves AND BOTTOM 5
likely-net-negative ones."""),
    ("M5-future-retrospective",
     """Your lens: 6-month retrospective from 2026-11-25.  What will the
operator wish they had done differently?  What features will they regret
building?  What features will they wish they had built sooner?  What
architectural decisions made today will haunt them?  Be specific —
name actual rows / shifts / decisions that will look right or wrong in
hindsight."""),
]


def _build_prompt(persona_id: str, lens: str, source: str) -> str:
    return f"""# Strategic planning panel retry — {persona_id} (mimo)

Operator directive 2026-05-25: dispatch 15-engine strategic plan.
Main run had MiMo fail (context overflow); this retry uses a smaller
source pack focused on the 2 strategic planning docs.

Your specific lens:

> {lens}

## Source pack (focused subset)

{source}

## Output requirements

Produce a STRUCTURED response with EXACTLY these sections:

### 1. Lens-specific findings
3-7 specific findings only your lens can surface.  Grounded in
VERBATIM quotes from the source pack.

### 2. Recommended SHIP list (top 3-5 rows to do FIRST)
Concrete rows or shifts (use names from the source pack).  Each
with one-sentence why.

### 3. Recommended DROP list (top 2-4 rows to NOT do)
What's in the backlog that should be cut + why.

### 4. Recommended ADD list (top 1-3 NEW rows worth adding)
Missing rows + pitch + effort estimate (S/M/L).

### 5. Single most important recommendation
One sentence.  If the operator only does ONE thing from your lens,
what is it?

Be brutally honest.  Be specific.  Output Markdown.
"""


def _dispatch(persona_id: str, lens: str, source: str) -> dict:
    started = time.monotonic()
    out_path = OUT_DIR / f"mimo_{persona_id}.md"
    try:
        eng = get_engine("mimo", prefer_dpapi=False)
    except RuntimeError as exc:
        return {"persona_id": persona_id, "ok": False,
                "error": str(exc), "elapsed_s": time.monotonic() - started}
    prompt = _build_prompt(persona_id, lens, source)
    try:
        resp = eng.dispatch(prompt, "mimo-v2.5-pro", {"max_tokens": 6000})
    except Exception as exc:
        return {"persona_id": persona_id, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        return {"persona_id": persona_id, "ok": False,
                "error": resp.error or "(empty)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"persona_id": persona_id, "ok": True,
            "elapsed_s": elapsed, "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out}


def main() -> int:
    source = _load_small_pack()
    print(f"[mimo-retry] source: {len(source)} chars, "
          f"{len(PERSONAS)} personas")
    started = time.monotonic()
    results = []
    with _cf.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_dispatch, pid, lens, source): pid
            for pid, lens in PERSONAS
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s {r.get('tokens_in', 0)}/"
                     f"{r.get('tokens_out', 0)}t" if r["ok"]
                     else (r.get("error") or "")[:60])
            print(f"[mimo-retry] {flag} {r['persona_id']:<28}  {extra}")
            results.append(r)
    print(f"\n[mimo-retry] {sum(1 for r in results if r['ok'])}/5 "
          f"in {time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
