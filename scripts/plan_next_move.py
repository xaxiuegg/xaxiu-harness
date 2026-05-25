"""Multi-engine planning: 'what should we do next while 24h test cooks?'

Operator energy: 'I can't sit idle'.  Each engine gets the FULL session
context + a distinct lens, then proposes a concrete next move.  No
abstract advice — every proposal must name a deliverable, a time
estimate, a cost estimate, and what it tests/ships.

Operator preference baked in: max_tokens=5000 (the W12-B directive
landed in commit feeb446).
"""
from __future__ import annotations

import concurrent.futures as _cf
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine

OUT_DIR = Path("coord/reviews/plan-next-move")
OUT_DIR.mkdir(parents=True, exist_ok=True)


SESSION_CONTEXT = """\
## Current state (2026-05-24, ~22:00 UTC)

### What's running
- Tag v1.0.0-rc.1 pushed (commit fbf31e8)
- 24h autonomous test in progress (started ~21:55 UTC, ~6h in)
- Observer armed: cron cadence every 60min, daily retro 23:00
- Watchdog: OK, last cycle ~12-40min ago
- Preflight: PASS-WITH-WARNINGS (4 ok, 2 warn, 0 fail)
- Cost spent today: $0.20 / $5 budget (4% used)
- Dashboard live at http://localhost:8765 with all 4 W12-A endpoints

### What just shipped this session (10 commits, 2026-05-24)
- W11 closeout: 12/12 production rows shipped
- W11-SDK-E2E-LIVE-ENGINE-PROOF: first real-engine validation
  (Kimi/DeepSeek/MiMo via harness.dispatch); fixed auto-bootstrap adapter
- 20-agent operator-review panel Round 1: 18/19 WAIT-FOR-WAVE-12
- W12-A: shipped 5 fixes addressing all 3 universal blockers
  (Windows cp1252 Unicode, dashboard 404s, watchdog jargon)
- 20-agent panel Round 2: 13/15 effective APPROVE-AND-SHIP
- v1.0.0-rc.1 tagged
- Just demonstrated: 3-engine parallel review of a student's project
  brief (Aquinas) — 6 findings, $0 cost, 2m 37s
- Just shipped: W12-B-MAX-TOKENS-DEFAULT-RAISE backlog row

### Wave 12-B backlog (in STATUS.csv)
- W12-MORNING-EMAIL-BRIEF (M, 4h): SMTP sender for daily harness pulse
- W12-LIVE-ENGINE-SMOKE-HARNESS (M, 3h): weekly CI step exercising
  real Kimi/DeepSeek/MiMo (current is mock-only)
- W12-DASHBOARD-COST-WIDGET-HTML (M, 3h): /api/cost works but HTML
  doesn't render it yet
- W12-DASHBOARD-L5-BANNER-HTML (M, 2h): same for /api/l5-events
- W12-MYPY-STRICT-GATE-CI (S, 1-2h): mypy --strict src/harness/_sdk.py
  in GitHub Actions
- W12-B-MAX-TOKENS-DEFAULT-RAISE (S, 2h): raise defaults to 8000,
  normalize param name across engines, add --quick flag

### Tests + coverage
- 2165 tests green
- 87% panel approval rate
- SDK proven against 3 production engines

### Operator profile
- Non-technical operator (per [[user_non_technical_role]] memory)
- Full dev authority on xaxiu-harness (commit/push/dispatch without
  per-action confirmation)
- 'I can't sit idle' — current vibe
- Just demonstrated comfort with multi-engine review for real work
- Just OK'd 'high max token output cap'

### Constraints
- 24h autonomous test SHOULD NOT be interrupted (the whole point is
  unattended survival)
- Cost cap $5/session (still have $4.80 of headroom)
- Engine cooldowns + circuit breakers active
- Don't touch warehouse project files (separate session scope)

### What I (Claude in-session) think is on the table
1. Drive Wave 12-B rows via the harness itself (eat dog food)
2. Use the harness to do REAL work outside the harness (more student
   project reviews, draft documents, code audits)
3. Polish the operator-facing surface (dashboard HTML, README,
   landing page, docs)
4. Build something we'd actually use (chat wrapper, simpler CLI,
   IDE extension)
5. Stress-test the harness with adversarial inputs to find what
   breaks before real-day-use proves it
6. Sit quietly and let the 24h test finish (rejected by operator)
"""


PERSONAS = [
    ("kimi", "kimi-for-coding", "highest-fun-momentum",
     """You are advising on a Sunday evening hack session.  The operator
just shipped v1.0.0-rc.1 of their multi-engine LLM dispatch harness
and is in a 'can't sit idle' mood — momentum is the constraint, not
budget or time.  The 24h autonomous test is humming in the background
and must not be interrupted.

Your lens: HIGHEST FUN + MOMENTUM.  What's the move that:
- Produces a visible, satisfying outcome by end of session
- Doesn't require permission-asking or scope-debate
- Builds on the existing momentum (don't pivot, extend)
- Is genuinely enjoyable to drive

Output: rank 3-5 specific moves with for each:
- One-sentence pitch
- Concrete deliverable
- Time estimate (30min / 1h / 2h / 3h)
- Why this beats sitting idle
End with: your single top recommendation + the first concrete command
to execute."""),

    ("deepseek", "deepseek-v4-flash", "highest-engineering-roi",
     """You are a sharp engineering reviewer asked: 'given 1-3 hours of
operator + agent time tonight, what's the highest-engineering-ROI
move?'  The harness is at v1.0.0-rc.1, panel-approved, 24h test
running, $4.80 budget headroom.

Your lens: HIGHEST ENGINEERING ROI.  ROI = (value delivered) /
(time + complexity + risk).  Specifically value to:
- The eventual non-technical operator's UX
- The agent calling harness.dispatch from a fresh clone
- The harness's audit trail / debuggability
- The Wave 12-B backlog burndown

Output: rank 3-5 specific moves with for each:
- One-sentence pitch
- The concrete code/files that would change
- Time estimate
- Why this ROI beats the alternatives
- One specific risk
End with: your single top recommendation + the first concrete command
to execute.  Be brutally honest about which Wave 12-B rows are
high-ROI vs busy-work."""),

    ("mimo", "mimo-v2.5-pro", "long-term-direction",
     """You are advising on harness DIRECTION.  v1.0.0-rc.1 is panel-
approved but real-day-use hasn't happened yet (24h test is the first).
There are concrete Wave 12-B rows AND interesting longer-arc moves
(IDE extension, marketplace listing, blog post, dogfood-driven
features, comparative positioning vs Aider/Cursor/Claude Code).

Your lens: LONG-TERM DIRECTION.  What single Sunday-evening move best
advances the project's trajectory over the next month?  Should the
operator:
- Burn down Wave 12-B (incrementalism)?
- Pivot to dogfooding (use the harness on a real non-harness project)?
- Invest in narrative (README + landing page + demo video)?
- Recruit users (post to HN/Reddit/Discord)?
- Something else entirely?

Output: 3-4 strategic directions with for each:
- One-paragraph case
- What it forecloses (opportunity cost)
- Time estimate
- What success looks like in 1 month
End with: which direction the operator should pick AND why this is the
inflection point that matters."""),
]


def _build_prompt(lens: str) -> str:
    return f"""{lens}

---

## Full session context

{SESSION_CONTEXT}
"""


def _dispatch(engine: str, model: str, lens_id: str, lens: str) -> dict:
    started = time.monotonic()
    out_path = OUT_DIR / f"{engine}_{lens_id}.md"
    try:
        eng = get_engine(engine, prefer_dpapi=False)
        # W12-B-MAX-TOKENS-DEFAULT-RAISE preference: high cap per
        # operator directive 2026-05-24.  5000 sufficient for 4-5
        # ranked recommendations with detail.
        resp = eng.dispatch(_build_prompt(lens), model,
                             {"max_tokens": 5000})
    except Exception as exc:
        return {"engine": engine, "lens": lens_id, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        return {"engine": engine, "lens": lens_id, "ok": False,
                "error": resp.error or "(empty)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"engine": engine, "lens": lens_id, "ok": True,
            "elapsed_s": elapsed, "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out, "cost_usd": resp.cost_usd}


def main() -> int:
    print(f"[plan] dispatching {len(PERSONAS)} engines in parallel...")
    started = time.monotonic()
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_dispatch, eng, mdl, lid, lens): lid
            for eng, mdl, lid, lens in PERSONAS
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"{r.get('tokens_in', 0)}/{r.get('tokens_out', 0)} "
                     f"${r.get('cost_usd', 0):.4f}" if r["ok"]
                     else r.get("error", "")[:60])
            print(f"[plan] {flag} {r['engine']:<10} "
                  f"{r['lens']:<32} {extra}")
            results.append(r)
    elapsed = time.monotonic() - started
    print(f"\n[plan] {sum(1 for r in results if r['ok'])}/3 in {elapsed:.0f}s")
    print(f"[plan] artifacts: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
