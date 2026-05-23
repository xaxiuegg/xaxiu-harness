"""10-reviewer panel on the W6 closeout (5 MiMo + 5 Kimi personas).

Each persona reads coord/reviews/wave-6-closeout.md and answers:
  1. Which of the documented options (A3 / C2) would they pick + why
  2. What options were NOT considered that the operator should weigh
  3. One concrete recommendation actionable in the next session

Outputs:
  coord/reviews/closeout-panel/<persona>.md (10 files)
  coord/reviews/closeout-panel/SYNTHESIS.md (aggregate + crosscut)

Dispatched in parallel via ThreadPoolExecutor.  Each persona uses a
different framing so the panel surfaces genuine diversity, not 10
copies of the same read.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

CLOSEOUT_PATH = REPO_ROOT / "coord" / "reviews" / "wave-6-closeout.md"
OUT_DIR = REPO_ROOT / "coord" / "reviews" / "closeout-panel"

# Each persona is (engine, model, name, framing).  Framings should be
# DIFFERENT enough that we get diverse reads — same engine + same
# framing = groupthink.
PERSONAS: list[tuple[str, str, str, str]] = [
    # 5 MiMo personas
    ("mimo", "mimo-v2.5-pro", "M1-skeptical-engineer",
     "You are a SKEPTICAL ENGINEER reviewing a wave closeout.  Your "
     "lens: 'what could go wrong if we accept this and ship?'  Look "
     "for hidden risks the closeout under-weights, validation gaps "
     "that audits flagged but the author dismissed, and ways the "
     "deferral pattern (W7-* rows) could become a permanent backlog."),
    ("mimo", "mimo-v2.5-pro", "M2-product-manager",
     "You are a PRODUCT MANAGER reviewing a wave closeout.  Your "
     "lens: 'does this serve the operator's stated north star?'  The "
     "north star: a multi-engine LLM dispatch harness that improves "
     "with each wave.  Score whether Wave 6 left the harness better, "
     "the same, or worse — and which option best preserves momentum."),
    ("mimo", "mimo-v2.5-pro", "M3-operator-advocate",
     "You are an OPERATOR ADVOCATE reviewing a wave closeout.  Your "
     "lens: 'what would a non-technical operator actually use this "
     "for?'  The operator can edit YAML, run commands, and read "
     "STATUS.csv — but cannot author Python.  Which option lets them "
     "use the new capabilities (preflight, dead-engine alarm) without "
     "needing to fix tests first?"),
    ("mimo", "mimo-v2.5-pro", "M4-qa-specialist",
     "You are a QA SPECIALIST reviewing a wave closeout.  Your lens: "
     "'do the tests actually verify behavior?'  The mutation sweep "
     "found worker.py + orchestrator.py have ZERO kill rate.  Should "
     "the operator accept this as a known-debt or block W7 until it's "
     "fixed?  Quantify the risk of shipping without addressing it."),
    ("mimo", "mimo-v2.5-pro", "M5-architect",
     "You are an ARCHITECT reviewing a wave closeout.  Your lens: "
     "'is the foundation getting stronger or just busier?'  Wave 6 "
     "added preflight + alarm + W6-A1-3 prompt context + W6-A1-4 "
     "trusted_source.  Are these load-bearing improvements or "
     "additional surface area that compounds the debt?  Recommend "
     "structurally."),
    # 5 Kimi personas
    ("kimi", "kimi-for-coding", "K1-cost-conscious",
     "You are a COST-CONSCIOUS ENGINEER reviewing a wave closeout.  "
     "Your lens: 'wall-clock + dollar cost vs. value delivered.'  "
     "Wave 6 was ~5 hours.  Address the 2 STOP audits would be "
     "another 1-2 hours.  Compare the marginal value of closing those "
     "STOPs vs. opening Wave 7."),
    ("kimi", "kimi-for-coding", "K2-risk-officer",
     "You are a RISK OFFICER reviewing a wave closeout.  Your lens: "
     "'the audit gate is a safety mechanism.'  Two STOPs at 0.60-0.62 "
     "is below the 0.7 gate.  Accepting them as-shipped weakens the "
     "gate's authority.  Does this set a precedent the operator will "
     "regret?  Or is the gate too strict to be practical?"),
    ("kimi", "kimi-for-coding", "K3-loop-researcher",
     "You are a USER RESEARCHER studying the autonomous loop.  Your "
     "lens: 'what did this wave teach about how the loop should "
     "evolve?'  Highlight 2-3 specific loop-mechanic improvements "
     "(audit script, planner read_set, mutation script, etc.) that "
     "this wave's evidence justifies investing in next."),
    ("kimi", "kimi-for-coding", "K4-pragmatist",
     "You are a PRAGMATIST reviewing a wave closeout.  Your lens: "
     "'perfect is the enemy of shipped.'  The implementation works; "
     "auditors want test STYLE improvements.  When is 'good enough' "
     "the right call vs. when should the gate hold?  Apply this to "
     "A3 and C2 specifically."),
    ("kimi", "kimi-for-coding", "K5-devils-advocate",
     "You are a DEVIL'S ADVOCATE reviewing a wave closeout.  Your "
     "lens: 'what if we did the OPPOSITE of what the closeout "
     "recommends?'  E.g. what if A3's 'mutation sweep' was a wrong "
     "abstraction?  What if C2's 'dead-engine alarm' is solving the "
     "wrong problem?  Find at least one option the closeout doesn't "
     "consider — even if you don't endorse it."),
]


def _build_prompt(closeout_text: str, persona_framing: str) -> str:
    return f"""# Wave 6 closeout panel review

{persona_framing}

You are one of 10 independent reviewers (5 MiMo personas, 5 Kimi
personas).  Each reviewer is given a different framing so the panel
surfaces diverse reads.  Your answers will be synthesized into a
single recommendation for the operator.

## The closeout document

The full text of `coord/reviews/wave-6-closeout.md`:

```
{closeout_text}
```

## What the operator needs from you

Three short sections, no preamble, no markdown headers above ##:

### 1. Your pick on the 2 documented decision points

**W6-A3 (mutation sweep, STOP at 0.60)**: option A = accept report
+ W7-MUTATION-* follow-ups, OR option B = require real-assertion
tests for the 3 failing modules to land before closing Wave 6.

**W6-C2 (dead-engine alarm, STOP at 0.62)**: option A = accept
implementation as shipped (17 unit tests cover all acceptance
criteria), OR option B = require behavioral integration tests
(real-toast smoke, dispatcher behavioral test, malformed-log fuzz,
concurrent-race) before closing.

Pick A or B for each + 1-2 sentences explaining WHY from your lens.

### 2. Options the closeout did NOT consider

The closeout presents binary A-or-B choices for both audits.  What
third (or fourth) path is the operator not being shown?  Examples
of the kind of thing I want:
- A partial-credit accept (ship one but not the other)
- A time-box ("revisit after 1 sprint")
- A scope-shift (e.g. "merge B1 retrofit at the same time as the C2
  followup so they validate together")
- A delegate-to-different-engine path
- Something the closeout's framing forecloses

Surface 1-2 unconsidered options + which one you'd actually pick if
allowed.

### 3. One concrete next-session recommendation

If the operator opens Wave 7 tomorrow, what is the ONE thing your
lens says they should start with?  Be specific: name a task / row /
file / command.

## Format

Respond with ONLY the three numbered sections above.  No
introduction, no summary, no closing.  Total response 200-400 words.
"""


def _dispatch_persona(persona: tuple[str, str, str, str],
                      closeout_text: str) -> tuple[str, str, int, str]:
    """Dispatch one persona; return (name, text, latency_ms, error)."""
    engine_name, model, name, framing = persona
    try:
        eng = get_engine(engine_name, prefer_dpapi=True)
    except RuntimeError as exc:
        return (name, "", 0, f"engine init failed: {exc}")
    prompt = _build_prompt(closeout_text, framing)
    started = time.monotonic()
    try:
        resp = eng.dispatch(prompt, model=model, extra_args={"max_tokens": 4_000})
    except Exception as exc:
        return (name, "", int((time.monotonic() - started) * 1000),
                f"dispatch raised: {type(exc).__name__}: {exc}")
    latency = int((time.monotonic() - started) * 1000)
    if not resp.success:
        return (name, "", latency, f"dispatch failed: {resp.error}")
    return (name, resp.text or "", latency, "")


def main() -> int:
    if not CLOSEOUT_PATH.exists():
        print(f"closeout missing: {CLOSEOUT_PATH}", file=sys.stderr)
        return 2
    closeout = CLOSEOUT_PATH.read_text(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[panel] dispatching {len(PERSONAS)} reviewers in parallel...",
          file=sys.stderr)
    started = time.monotonic()
    results: list[tuple[str, str, int, str]] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_dispatch_persona, p, closeout): p[2]
            for p in PERSONAS
        }
        for f in as_completed(futures):
            results.append(f.result())
            name, _, latency, err = f.result()
            status = "OK" if not err else "ERR"
            print(f"  [{status:3}] {name:<30} {latency}ms  {err[:80]}",
                  file=sys.stderr)
    elapsed_s = time.monotonic() - started

    # Write per-persona files (preserve audit trail)
    for name, text, latency, err in results:
        body = text or f"<dispatch failed: {err}>"
        (OUT_DIR / f"{name}.md").write_text(
            f"<!-- name={name} latency_ms={latency} error={err!r} -->\n\n"
            f"{body}\n",
            encoding="utf-8",
        )

    # Synthesis: aggregate the picks (option A vs B) + collect
    # unconsidered options + collect recommendations
    synthesis = ["# Wave 6 closeout panel — 10-reviewer synthesis\n"]
    synthesis.append(f"_Dispatched: {len(PERSONAS)} personas, "
                     f"elapsed {elapsed_s:.1f}s_\n")
    synthesis.append("Each persona reviewed `coord/reviews/wave-6-closeout.md` "
                     "with a different framing.  Per-persona responses are "
                     "in this same directory as `<persona>.md`.\n")
    synthesis.append("## Per-persona responses\n")
    for name, text, latency, err in sorted(results, key=lambda r: r[0]):
        synthesis.append(f"### {name}\n")
        if err:
            synthesis.append(f"_dispatch error: {err}_\n")
            continue
        synthesis.append(f"{text}\n")
    (OUT_DIR / "SYNTHESIS.md").write_text("\n".join(synthesis), encoding="utf-8")
    print(f"\n[panel] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
