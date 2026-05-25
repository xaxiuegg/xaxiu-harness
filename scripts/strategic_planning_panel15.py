"""15-engine strategic planning panel: how should we approach the
operator/SDK shifts + Wave 13 sequencing strategically?

Operator directive 2026-05-25: 'dispatch 5 high context high output
kimi and mimo and deepseek, reconciliate and plan out how we should
approach this strategically. Have a clear forward plan first before
we proceed.'

5 Kimi + 5 MiMo + 5 DeepSeek personas, each with a distinct lens, all
fed the SAME source pack (master audit + Horizon C internal-tool plan
+ bloat audit + Wave 13 backlog + STATUS.csv recent + AGENT_QUICKSTART
+ runbook).

High output: max_tokens=8000 per the W12-B directive.
High context: source pack ~60KB.
Cost: ~$0.02-0.05 total (Kimi + MiMo subscription = $0; DeepSeek paid
at high output).
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
OUT_DIR.mkdir(parents=True, exist_ok=True)


SOURCE_FILES = [
    "coord/reviews/master-audit-2026-05-25.md",
    "coord/reviews/horizon-c-internal-tool-plan.md",
    "coord/reviews/bloat-audit-2026-05-25.md",
    "docs/AGENT_QUICKSTART.md",
    "docs/INTERNAL_OPERATOR_RUNBOOK.md",
]


def _load_source_pack() -> str:
    parts: list[str] = []
    for rel in SOURCE_FILES:
        path = REPO / rel
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"\n\n=== FILE: {rel} ===\n\n{text}")
    # Recent STATUS.csv tail (last 60 rows)
    status_path = REPO / "coord" / "STATUS.csv"
    if status_path.exists():
        lines = status_path.read_text(encoding="utf-8").splitlines()
        recent = "\n".join(lines[-60:])
        parts.append(f"\n\n=== FILE: coord/STATUS.csv (last 60 rows) ===\n\n"
                     f"{recent}")
    return "".join(parts)


PERSONAS = [
    # --- KIMI 5 ---
    ("K1-first-principles", "kimi", "kimi-for-coding",
     """You are a first-principles reasoner.  Strip away the existing
plan + start from scratch: GIVEN the current state of the harness
(v1.0.0-rc.1, 2197 tests, panel-approved, 14 commits today, internal-
tool framing), what SHOULD the primary user-experience of this tool be
1 year from now?  Reason from scratch about what users (operator AND
agent) ACTUALLY do day-to-day, not what they MIGHT do.  Then critique
the Tier 1-3 shift map + Wave 13 backlog against that first-principles
vision.  What's missing?  What's over-built?  What's exactly right?"""),

    ("K2-agentic-trust", "kimi", "kimi-for-coding",
     """You are an AI coding agent (Claude / GPT / Cursor) considering
whether to adopt this harness for production use.  Read the SDK
surface, the AGENT_QUICKSTART, the failure modes documented in the
bloat audit, and the operator's role.  What would make you TRUST this
SDK enough to depend on it for 6+ months of real client work?  What
would make you walk away?  What single change to the SDK would most
increase your trust?"""),

    ("K3-operator-1year", "kimi", "kimi-for-coding",
     """You are the operator 1 year from now (2027-05-25).  Walk
through your typical day: what's the first command you run in the
morning?  How often do you touch the harness?  Which CLI verbs have
you forgotten?  Which auto-defaults were genius?  Which auto-defaults
caused a bug you only noticed weeks later?  What's the harness's role
in your workflow vs the role you imagined a year ago?  What advice
would you give yourself 1 year ago (today's operator)?"""),

    ("K4-comparative-positioning", "kimi", "kimi-for-coding",
     """You are an expert comparing the harness against Claude Code CLI,
Aider, Cursor, OpenDevin, and other dev-agent tools.  This is an
INTERNAL tool, so don't optimize for distribution — optimize for the
operator's own use.  Where does the harness uniquely shine (keep +
double down)?  Where does it duplicate effort that those tools do
better (drop)?  Where should it integrate WITH those tools rather than
compete?  Give specific verdicts on: (a) the multi-engine SDK, (b)
`harness review`, (c) the coord pipeline, (d) the observer + watchdog,
(e) the dashboard."""),

    ("K5-architectural-split", "kimi", "kimi-for-coding",
     """You are a software architect reviewing the operator/SDK split.
Currently the SDK is 3 functions + DispatchResult; the operator-facing
surface is 30+ CLI verbs + runbook + STATUS.csv discipline + multiple
docs.  Is this split right?  Or should it be: (a) SDK does much more
(making the operator surface smaller), (b) more should be CLI (making
the SDK smaller), (c) introduce a third layer (operator-CLI for humans,
agent-SDK for programs, deep-internals for maintainers).  Give a
concrete architectural recommendation with files-that-change."""),

    # --- MIMO 5 ---
    ("M1-risk-and-safety", "mimo", "mimo-v2.5-pro",
     """Your lens: risk + safety review of the Tier 1-3 shifts AND the
Wave 13 remaining rows.  For each proposed shift + each backlog row,
identify: (a) the worst-case silent failure, (b) the detection-latency
(how long before the operator notices), (c) the blast radius (what
breaks for whom), (d) the rollback cost.  Then RANK the proposed work
by risk-adjusted ROI.  Be brutal — most plans look good until you
think about the silent-failure mode.  Specific things to evaluate:
auto-pick lens-set, auto-pick max_tokens, SDK auto-retry, auto-snapshot,
cost-cap pre-check, dispatch cache TTL, low-severity flag auto-close,
W13-AUDIT-JSONL, W13-DISK-PRUNE, W13-INSTALL-VERIFY."""),

    ("M2-sequencing-strategy", "mimo", "mimo-v2.5-pro",
     """Your lens: SEQUENCING.  Given finite operator attention (1-3h
of focused work per evening, maybe 5h on weekends), what's the OPTIMAL
order to ship the remaining work?  Wave 13 has 6 unshipped rows
(audit JSONL, disk prune, install verify, secrets rotation, CI drift
gate, lock deps).  The bloat audit proposes Tier 1-3 shifts (8 rows).
The Horizon C plan has Wave 14-17 (15+ rows).  Order all of these by
sequence — with dependencies, parallel tracks where they exist, and
explicit 'STOP and re-evaluate' decision points.  Show the operator
EXACTLY which row to ship Monday, Tuesday, etc., for the next 2 weeks."""),

    ("M3-hallucination-deep-dive", "mimo", "mimo-v2.5-pro",
     """Your lens: hallucination vectors not yet identified.  The bloat
audit names 6 vectors observed in the current session.  What ELSE could
go wrong as the harness grows?  Specifically think about: SDK signature
changes that break old caller patterns; CLI verb deprecation policy;
config-key drift between YAML schemas; engine-model coupling that
changes when the engine vendor renames a model; STATUS.csv schema
migrations; observer state schema migrations; the dispatch cache's
binary compatibility across harness versions.  For each vector you
identify, propose a SINGLE specific mitigation (with effort estimate)
the harness should adopt."""),

    ("M4-roi-sequence-rigor", "mimo", "mimo-v2.5-pro",
     """Your lens: calculate ROI for every proposed row + shift in
operator-hours-saved-per-implementation-hour.  Be RIGOROUS: estimate
the actual hours each row saves the operator over 6 months (e.g., 'auto-
pick lens-set saves the operator ~2 hours of remember-the-flag
friction over 6 months') and divide by implementation hours.  Rank
ALL proposed work (Tier 1-3 shifts + Wave 13 rows + cross-engine-
review-flagged rows + Horizon C plan rows) by ROI.  Then identify the
TOP 5 highest-ROI moves AND the BOTTOM 5 that are likely net-negative
(burn implementation time without recouping operator burden)."""),

    ("M5-future-retrospective", "mimo", "mimo-v2.5-pro",
     """Your lens: 6-month retrospective from 2026-11-25.  Looking BACK
at what was actually built between today and 6 months from now: what
will the operator wish they had done differently?  What features will
they regret building?  What features will they wish they had built
sooner?  What architectural decisions made today will haunt them?  What
operational habits will have proven essential?  What pivots will have
happened?  Be specific — name actual rows / shifts / decisions that
will look right or wrong in hindsight."""),

    # --- DEEPSEEK 5 ---
    ("D1-tier1-tech-critique", "deepseek", "deepseek-v4-flash",
     """Your lens: technical critique of the Tier 1 shifts (auto-pick
lens-set, auto-pick max_tokens, unify harness.review() as SDK).  For
each shift, audit: (a) the API design — does the signature make sense
with the rest of the SDK?  (b) the failure modes — what happens when
the auto-default is wrong?  (c) the override mechanism — can the
operator + agent actually override it cleanly?  (d) the test surface
— what tests must accompany this shift?  (e) the backwards-compat —
what existing callers break?  Be specific.  Propose exact function
signatures + test plans."""),

    ("D2-sdk-api-merge-audit", "deepseek", "deepseek-v4-flash",
     """Your lens: should `harness.dispatch()` and `harness.review()`
ACTUALLY merge into a single SDK function?  Or stay separate?  Argue
both sides.  Then RULE on the right design.  Consider: (a) is review
just dispatch + synthesis, or fundamentally different?  (b) what
breaks if they merge?  (c) what stays awkward if they don't?  (d) the
agent's mental model.  (e) future extensions (audit, compare, etc.)
— do they extend dispatch or review?  Give a concrete API design
including: the unified function signature (if merging), the migration
path for existing callers, the deprecation timeline."""),

    ("D3-auto-default-risk-audit", "deepseek", "deepseek-v4-flash",
     """Your lens: for EACH proposed auto-default in Tier 1-3 (auto
lens-set, auto max_tokens, auto-snapshot, auto-retry, cost pre-check,
L5 inline, cache TTL, flag auto-close), enumerate the SILENT-FAILURE
modes.  Specifically: what's the WORST thing that could silently
happen because the auto-default picked wrong + the operator didn't
notice for 2 weeks?  Rank by severity (LOW/MED/HIGH/CRITICAL).  For
each CRITICAL or HIGH, propose a specific guardrail: a test, a log
line, an observer flag, or 'do not ship this auto-default'."""),

    ("D4-test-coverage-plan", "deepseek", "deepseek-v4-flash",
     """Your lens: comprehensive test plan for the proposed work
(Tier 1-3 shifts + Wave 13 rows).  For each row, name SPECIFIC test
cases that must exist before ship.  Distinguish: (a) happy-path unit
tests, (b) failure-mode tests, (c) integration tests, (d) regression
tests against the existing 2197 tests, (e) security tests (for backup,
secrets, plugin).  Be specific — name the test function name + what
it asserts.  Estimate test-writing effort separately from
implementation effort.  Identify which rows have a HIGH test-to-impl
ratio (>1.5x) and decide whether that means the row is risky or just
needs more care."""),

    ("D5-cross-cutting-concerns", "deepseek", "deepseek-v4-flash",
     """Your lens: cross-cutting concerns across the proposed work.
Specifically audit: (a) SECURITY — backup encryption, secrets in
audit-jsonl, plugin code-injection, VPS-to-laptop reachability.
(b) PERFORMANCE — does auto-snapshot block dispatches?  Does cost-cap
pre-check add latency to every dispatch?  Does the cache TTL prune
during read paths?  (c) MAINTAINABILITY — will the operator (or
future-Claude) be able to debug an unexpected auto-default-driven
behavior?  Do we have enough observability?  (d) COMPATIBILITY — do
the shifts break the W11_E2E_SDK_PROOF claims?  Do they break the
panel's APPROVE-AND-SHIP signal?  For each cross-cutting concern,
identify the SPECIFIC mitigation that must be in place before the
related row ships."""),
]


def _build_prompt(persona_id: str, engine: str, lens: str, source: str) -> str:
    return f"""# Strategic planning panel — {persona_id} ({engine})

You are persona **{persona_id}** ({engine}) on a 15-engine strategic
planning panel.  The operator has 1-3 hours of evening time + 5h on
weekends, and they want a STRATEGIC FORWARD PLAN — not opinions, not
brainstorming, but a concrete sequenced plan they can act on Monday.

Your specific lens:

> {lens}

## Source pack

The full context of where the project is:

{source}

## Output requirements

Produce a STRUCTURED response with EXACTLY these sections:

### 1. Lens-specific findings
Your unique contribution.  3-7 specific findings only your lens can
surface.  Each grounded in a VERBATIM quote from the source pack.

### 2. Recommended SHIP list (your top 3-5 rows to do FIRST)
Concrete rows or shifts (use the names from the source pack:
W13-AUDIT-JSONL, Tier 1 Shift A, etc.).  For each: one-sentence why.

### 3. Recommended DROP list (your top 2-4 rows to NOT do)
What's in the current backlog that should be cut.  For each: why
this is net-negative.

### 4. Recommended ADD list (your top 1-3 NEW rows worth adding)
Things missing from the backlog that should be in it.  For each:
one-sentence pitch + effort estimate (S/M/L).

### 5. Single most important recommendation
One sentence.  If the operator only does ONE thing from your lens,
what is it?

Be BRUTALLY honest.  Be SPECIFIC.  Reference verbatim quotes from
the source pack.  Output Markdown.
"""


def _dispatch(persona_id: str, engine: str, model: str, lens: str,
               source: str, max_tokens: int = 8000) -> dict:
    started = time.monotonic()
    out_path = OUT_DIR / f"{engine}_{persona_id}.md"
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        out_path.write_text(f"# {persona_id} engine_init_failed\n\n{exc}",
                             encoding="utf-8")
        return {"persona_id": persona_id, "ok": False,
                "error": f"engine init failed: {exc}",
                "elapsed_s": time.monotonic() - started}
    prompt = _build_prompt(persona_id, engine, lens, source)
    try:
        resp = eng.dispatch(prompt, model, {"max_tokens": max_tokens})
    except Exception as exc:
        out_path.write_text(
            f"# {persona_id} dispatch_exception\n\n{exc}",
            encoding="utf-8",
        )
        return {"persona_id": persona_id, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        out_path.write_text(
            f"# {persona_id} engine_returned_empty\n\n{resp.error}",
            encoding="utf-8",
        )
        return {"persona_id": persona_id, "ok": False,
                "error": resp.error or "(empty)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"persona_id": persona_id, "ok": True,
            "elapsed_s": elapsed, "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out, "cost_usd": resp.cost_usd,
            "engine": engine}


def main() -> int:
    print(f"[panel] loading source pack...")
    source = _load_source_pack()
    print(f"[panel] source pack: {len(source)} chars across "
          f"{len(SOURCE_FILES)} files + STATUS.csv tail")
    print(f"[panel] dispatching {len(PERSONAS)} personas, "
          f"max_concurrent=8...")
    started = time.monotonic()
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_dispatch, pid, engine, model, lens, source): pid
            for pid, engine, model, lens in PERSONAS
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"{r.get('tokens_in', 0)}/{r.get('tokens_out', 0)}t "
                     f"${r.get('cost_usd', 0):.4f}" if r["ok"]
                     else (r.get("error") or "(none)")[:80])
            print(f"[panel] {flag} {r['persona_id']:<28} "
                  f"{r.get('engine', '?'):<10} {extra}")
            results.append(r)
    elapsed = time.monotonic() - started
    n_ok = sum(1 for r in results if r["ok"])
    total_cost = round(sum(r.get("cost_usd", 0) for r in results), 4)
    print(f"\n[panel] {n_ok}/{len(results)} successful in {elapsed:.0f}s")
    print(f"[panel] total cost: ${total_cost:.4f}")
    print(f"[panel] artifacts: {OUT_DIR}")
    return 0 if n_ok >= len(results) * 0.75 else 1


if __name__ == "__main__":
    sys.exit(main())
