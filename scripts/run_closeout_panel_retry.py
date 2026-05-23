"""Retry the 3 failed Kimi reviewers from the panel (K1, K2, K3).

The original run hit empty responses on Kimi — likely an SSE parse
edge case on long prompts.  This retry shortens the prompt + uses
a different framing to get past the empty-response failure mode.
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

PERSONAS_RETRY: list[tuple[str, str, str, str]] = [
    ("kimi", "kimi-for-coding", "K1-cost-conscious",
     "COST-CONSCIOUS ENGINEER lens: wall-clock + dollar cost vs. "
     "value delivered.  Wave 6 was ~5 hours.  Address the 2 STOP "
     "audits would be another 1-2 hours.  Compare marginal value."),
    ("kimi", "kimi-for-coding", "K2-risk-officer",
     "RISK OFFICER lens: the audit gate is a safety mechanism.  Two "
     "STOPs at 0.60-0.62 is below the 0.7 gate.  Does accepting them "
     "weaken the gate?  Or is the gate too strict?"),
    ("kimi", "kimi-for-coding", "K3-loop-researcher",
     "LOOP RESEARCHER lens: what did this wave teach about how the "
     "loop should evolve?  Name 2-3 loop-mechanic improvements (audit "
     "script, planner read_set, mutation script) this wave justifies "
     "investing in next."),
]

# Tighter prompt — Kimi seems to truncate on long inputs.  Skip the
# closeout doc full embed and instead summarize the relevant facts.
CLOSEOUT_SUMMARY = """\
Wave 6 closeout (full doc at coord/reviews/wave-6-closeout.md, summary):

W6-A3 mutation sweep STOPped at audit confidence 0.60.
  - 5 modules x 5 mutations sweep
  - PASS: dispatcher.py (avg=17.3), integrator.py (avg=5.0)
  - FAIL: concrete.py (avg=1.0), worker.py (avg=0.0), orchestrator.py (avg=0.0)
  - 3 W7-MUTATION-* follow-up rows queued
  - Auditor reads spec bullet 1 as binary gate; deliverable is the report

W6-C2 dead-engine alarm STOPped at audit confidence 0.62.
  - Implementation: src/harness/engine_alarm.py + dispatcher hook + preflight
  - 17 unit tests covering all acceptance criteria including
    fire->recover->re-fire state-machine cycle
  - Auditor wants: real-toast smoke, dispatcher behavioral test (not
    source grep), malformed-log fuzz, concurrent-race test

Documented options per audit:
  A3 option A = accept report + W7 follow-ups
  A3 option B = require real-assertion tests for 3 fail modules first
  C2 option A = accept (acceptance criteria met by unit tests)
  C2 option B = require behavioral integration tests

Wave 6 also shipped: A1 (3 engines green e2e), A1-1/2/3/4 sub-tasks,
A2 (live token tests), B1 partial (transport.py in worktree, retrofit
stalled), B2 (preflight verb), B3 (autonomous gate), C1 (hook scope).
Test count 1426 -> 1465. 14 commits pushed."""


def _build_prompt(persona_framing: str) -> str:
    return f"""Wave 6 closeout panel review.  You are a reviewer with:

{persona_framing}

{CLOSEOUT_SUMMARY}

Answer in ONLY these three numbered sections.  Keep total under 350 words.

1. Your pick on A3 (A or B) + 1 sentence why, then C2 (A or B) + 1 sentence why.

2. What options are NOT in the documented A/B for each?  Surface 1-2
   third paths and pick which you'd actually use.

3. One concrete next-session recommendation (specific task / file).

Start your answer with "1." — no preamble.
"""


def _dispatch_persona(persona: tuple[str, str, str, str]) -> tuple[str, str, int, str]:
    engine_name, model, name, framing = persona
    try:
        eng = get_engine(engine_name, prefer_dpapi=True)
    except RuntimeError as exc:
        return (name, "", 0, f"engine init failed: {exc}")
    prompt = _build_prompt(framing)
    started = time.monotonic()
    try:
        # Don't override max_tokens — Kimi reasoning eats budgets below
        # ~16K.  Default in concrete.py is 32K which leaves room for
        # both reasoning_content and content.
        resp = eng.dispatch(prompt, model=model, extra_args={})
    except Exception as exc:
        return (name, "", int((time.monotonic() - started) * 1000),
                f"dispatch raised: {type(exc).__name__}: {exc}")
    latency = int((time.monotonic() - started) * 1000)
    if not resp.success:
        return (name, "", latency, f"dispatch failed: {resp.error}")
    return (name, resp.text or "", latency, "")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[retry] dispatching {len(PERSONAS_RETRY)} reviewers...",
          file=sys.stderr)
    started = time.monotonic()
    results: list[tuple[str, str, int, str]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_dispatch_persona, p): p[2] for p in PERSONAS_RETRY}
        for f in as_completed(futures):
            results.append(f.result())
            name, text, latency, err = f.result()
            status = "OK" if (text.strip() and not err) else "EMPTY"
            print(f"  [{status:5}] {name:<30} {latency}ms  text_len={len(text)}  {err[:80]}",
                  file=sys.stderr)
    elapsed_s = time.monotonic() - started

    for name, text, latency, err in results:
        body = text or f"<dispatch failed: {err or 'empty response'}>"
        (OUT_DIR / f"{name}.md").write_text(
            f"<!-- name={name} latency_ms={latency} error={err!r} retry=1 -->\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
    print(f"\n[retry] elapsed {elapsed_s:.1f}s; "
          f"wrote {len(results)} files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
