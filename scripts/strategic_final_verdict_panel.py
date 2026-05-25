"""Final-verdict panel: each engine answers ALL questions, no specialization.

Operator directive 2026-05-25: 'each agent should each try each
perspective, don't let single engine specialize in one area'.

The earlier 15-engine run gave each engine 1 lens.  This run gives
each engine ALL the strategic questions in ONE comprehensive prompt,
producing 3 mega-opinions to synthesize.

Each engine answers:
  1. Convergent SHIP list — agree/disagree/amend
  2. Convergent DROP list — agree/disagree/amend
  3. Convergent ADD list — agree/disagree/amend
  4. 6 unresolved dissents — render YOUR ruling on each
  5. Single most important action this week

Source pack: SYNTHESIS.md from the prior 15-engine run + the prior
per-engine responses + the 2 strategic plan docs.  ~30-40KB total
(small enough for MiMo's context).

3 dispatches, max_tokens=8000 each.  Expected cost: $0 (subscription).
"""
from __future__ import annotations

import concurrent.futures as _cf
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO / "coord" / "reviews" / "strategic-planning-panel15-final-verdict"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_source() -> str:
    """Build the same source pack for all 3 engines."""
    parts: list[str] = []

    # The synthesis from the previous round (the convergent picks)
    synth = REPO / "coord" / "reviews" / "strategic-planning-panel15" / "SYNTHESIS.md"
    if synth.exists():
        parts.append(f"=== PRIOR SYNTHESIS (15-engine first round) ===\n\n"
                     f"{synth.read_text(encoding='utf-8', errors='replace')}")

    # The two strategic plan docs (small versions)
    for rel in ["coord/reviews/bloat-audit-2026-05-25.md",
                 "coord/reviews/horizon-c-internal-tool-plan.md"]:
        p = REPO / rel
        if p.exists():
            parts.append(f"\n\n=== {rel} ===\n\n"
                         f"{p.read_text(encoding='utf-8', errors='replace')}")

    return "".join(parts)


COMPREHENSIVE_PROMPT = """You are an expert reviewer rendering a final
judgment.  This is the SECOND ROUND of a strategic planning panel for
the xaxiu-harness project (a multi-engine LLM dispatch tool, internal-
tool framing).

The FIRST ROUND had 15 personas (5 Kimi + 5 MiMo + 5 DeepSeek), each
with a different specialized lens.  4 MiMo personas failed
(content-filter).  The 11 substantive responses converged on a SHIP
list + DROP list + ADD list, with 6 unresolved dissents.

The OPERATOR'S DIRECTIVE FOR THIS ROUND: 'each agent should each try
each perspective, don't let single engine specialize in one area'.

So: you (this specific engine) get the FULL source pack + are asked
to render YOUR comprehensive opinion across all the strategic questions
— not just one lens.  Three engines (Kimi, MiMo, DeepSeek) will each
answer the SAME questions; we look for cross-engine convergence and
flag dissents.

## Source pack (the prior synthesis + plan docs)

{source}

---

## Your task — answer ALL of these sections

### Section 1: SHIP list verdict
The prior panel converged on 5 SHIP items.  For each, render your
verdict (AGREE / DISAGREE / AMEND) with a one-sentence reason.

1. **W13-INSTALL-VERIFY** — universal #1 pick
2. **W13-AUDIT-JSONL** — universal #2 + foundational
3. **Tier 1 Shift F (auto max_tokens with safe floor)**
4. **`harness.review()` as new SDK function (NOT merge)**
5. **`harness.capabilities()` SDK function + surface in `today`**

### Section 2: DROP list verdict
The prior panel converged on dropping ~250-400h of work.  For each,
render YOUR verdict (AGREE / DISAGREE / KEEP-PARTIAL).

1. **W15 Plugin Architecture (entire wave)** — payback 10-15 years for solo
2. **W14-BEST-OF-N** — cost multiplier
3. **W16 Multi-User (entire wave)** — operator is solo
4. **W17 VPS hardening (entire wave)** — operator runs locally
5. **W13-PLUGIN-SANDBOX-PLAN** — trusted authors
6. **W13-BACKUP-ENCRYPTION (full AES)** — replaced by smaller redact scope
7. **W14-MISTRAL + W14-LOCAL-LLAMA** — 5-engine pool already enough

### Section 3: ADD list verdict
The prior panel surfaced 5 NEW rows worth adding.  For each, render
YOUR verdict (AGREE / DISAGREE / REPRIORITIZE).

1. **`harness.capabilities()` SDK function** (programmatic ground truth)
2. **CI doc-doc-sync gate** (grep `*.md` for `harness <verb>` + fail if missing)
3. **Schema versioning for all data structures** (STATUS.csv, cache, observer state)
4. **Auto-default guardrail framework** (CI test enforcing visible+overridable+auditable)
5. **W13-BACKUP-INTEGRITY** (SHA256 + verify on every backup)

### Section 4: Dissent rulings
The prior panel left 6 dissents.  For each, render YOUR ruling
(explicitly side with one option, no fence-sitting):

1. **Merge `dispatch` + `review` into one SDK function, OR keep separate?**
   Kimi said "unify" (ambiguous); DeepSeek said keep separate.

2. **Backup encryption — full AES, secrets-redact only, or skip entirely?**
   Kimi said skip (security theater); DeepSeek said critical.

3. **Auto-pick `max_tokens` from prompt length — sound heuristic or risky?**
   Kimi shipped enthusiastically; DeepSeek says prompt length ≠ output length.

4. **`harness whoami` as new CLI verb, SDK function, or both?**
   Kimi said new CLI verb; MiMo said don't add a verb, surface in `today`.

5. **Auto-snapshot before risky ops — ship now, defer, or never?**
   Kimi ship; DeepSeek defer until integrity ships; cross-cutting risk.

6. **Auto-close low-severity flags after 7d — ship, replace with
   auto-escalate, or never?**
   DeepSeek said replace with auto-escalate; others silent.

### Section 5: Add or remove any items from prior synthesis
What does YOUR comprehensive look reveal that the prior 1-lens-per-engine
approach missed?  Specifically:

- Is there a row in the DROP list that you'd actually KEEP?  Why?
- Is there a row in the SHIP list that you'd actually DROP?  Why?
- Is there a missing item — neither in prior SHIP/DROP/ADD lists — that
  the panel should consider?

### Section 6: Single most important action
If the operator can do ONE thing tomorrow morning, what is it?  One
sentence.  Justify in two sentences.

### Section 7: Confidence + dissent flagging
- Your overall confidence in the prior synthesis's forward plan
  (0.0-1.0).
- Which prior-synthesis claim do you LEAST trust?  Why?
- Where would you bet the prior synthesis is wrong?

Output Markdown.  Be brutally honest.  Don't sandbag.
"""


def _dispatch(engine: str, model: str, source: str) -> dict:
    started = time.monotonic()
    out_path = OUT_DIR / f"{engine}_final-verdict.md"
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        out_path.write_text(f"# {engine} engine_init_failed\n\n{exc}",
                             encoding="utf-8")
        return {"engine": engine, "ok": False,
                "error": str(exc),
                "elapsed_s": time.monotonic() - started}
    prompt = COMPREHENSIVE_PROMPT.format(source=source)
    try:
        resp = eng.dispatch(prompt, model, {"max_tokens": 8000})
    except Exception as exc:
        out_path.write_text(
            f"# {engine} dispatch_exception\n\n{exc}",
            encoding="utf-8",
        )
        return {"engine": engine, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        out_path.write_text(
            f"# {engine} engine_returned_empty\n\n{resp.error}",
            encoding="utf-8",
        )
        return {"engine": engine, "ok": False,
                "error": resp.error or "(empty)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"engine": engine, "ok": True,
            "elapsed_s": elapsed, "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out, "cost_usd": resp.cost_usd}


def main() -> int:
    source = _load_source()
    print(f"[final-verdict] source: {len(source)} chars")
    print(f"[final-verdict] dispatching 3 engines (Kimi/MiMo/DeepSeek) "
          f"each with FULL comprehensive prompt...")

    engines = [
        ("kimi", "kimi-for-coding"),
        ("mimo", "mimo-v2.5-pro"),
        ("deepseek", "deepseek-v4-flash"),
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
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"{r.get('tokens_in', 0)}/{r.get('tokens_out', 0)}t "
                     f"${r.get('cost_usd', 0):.4f}" if r["ok"]
                     else (r.get("error") or "")[:80])
            print(f"[final-verdict] {flag} {r['engine']:<10}  {extra}")
            results.append(r)
    print(f"\n[final-verdict] {sum(1 for r in results if r['ok'])}/3 "
          f"in {time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
