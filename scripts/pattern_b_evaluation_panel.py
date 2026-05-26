"""Pattern B independent-evaluation panel.

Operator request 2026-05-26: *"I need some separate independent views on
this, can you dispatch some mimo and deepseek panels to evaluate our
approach; use neutral language and perspective."*

Two lenses (architectural correctness + operational risk) x two engines
(MiMo + DeepSeek) = 4 dispatches.  Each engine gets the same source
pack (research artifact + smoke-test evidence + Pattern A/B context)
and is asked to evaluate, NOT validate.  Neutral framing throughout.

Output: coord/reviews/pattern-b-deep-research/<engine>_<lens>.md per
dispatch, plus a synthesis pass after.
"""
from __future__ import annotations

import concurrent.futures as _cf
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO / "coord" / "reviews" / "pattern-b-deep-research"
OUT_DIR.mkdir(parents=True, exist_ok=True)


LENSES: list[tuple[str, str]] = [
    ("architectural-correctness",
     "**Architectural correctness lens.**  Examine whether the design "
     "actually delivers what it claims (TOS-compliant subscription-tier "
     "access without provider termination risk).  Look for edge cases "
     "where the lift breaks: race conditions, env-var inheritance from "
     "the parent shell, provider-side detection signals beyond UA, "
     "subprocess identity vs spawning-process identity, what happens "
     "when ``--bare`` is missing or misconfigured.  Cite the strongest "
     "structural concern you can name and explain why it matters."),
    ("operational-risk",
     "**Operational risk lens.**  Examine what could go wrong in "
     "production.  Failure modes to consider: Claude Code CLI version "
     "drift, model-name drift on provider side, env-var leakage "
     "between concurrent dispatches, subprocess resource costs at "
     "panel scale (10+ parallel), provider-side rate limits, what "
     "happens if a panelist deletes their local Claude Code binary, "
     "interaction with W14-DISPATCH-HEALTH-AWARE-FALLBACK probe loop, "
     "audit-trail completeness.  Identify the highest-probability "
     "failure mode AND the highest-impact (different things may have "
     "different ranks).  Recommend one mitigation per top concern."),
]


def _load_source() -> str:
    """Build the source pack shown to all panelists."""
    parts: list[str] = []

    # The deep research artifact (just written)
    findings = OUT_DIR / "FINDINGS.md"
    if findings.exists():
        parts.append(
            f"=== Deep research: how each provider's Anthropic-compat "
            f"integration works (FINDINGS.md) ===\n\n"
            f"{findings.read_text(encoding='utf-8', errors='replace')}"
        )

    # The Pattern B implementation itself
    impl = REPO / "src" / "harness" / "engines" / "claude_code_subprocess.py"
    if impl.exists():
        parts.append(
            f"\n\n=== Implementation: src/harness/engines/"
            f"claude_code_subprocess.py ===\n\n"
            f"```python\n"
            f"{impl.read_text(encoding='utf-8', errors='replace')[:8000]}"
            f"\n```\n"
        )

    # Smoke-test evidence from earlier
    parts.append(
        "\n\n=== Live smoke test (2026-05-25 evening) ===\n\n"
        "Direct subprocess command:\n\n"
        "```bash\n"
        "ANTHROPIC_BASE_URL='https://token-plan-sgp.xiaomimimo.com/anthropic' \\\n"
        "ANTHROPIC_AUTH_TOKEN=$MIMO_API_KEY \\\n"
        "ANTHROPIC_API_KEY=$MIMO_API_KEY \\\n"
        "claude --print --bare --model mimo-v2.5-pro \\\n"
        "  --output-format json --max-budget-usd 0.05 \\\n"
        "  --no-session-persistence --permission-mode auto \\\n"
        "  'Reply with just OK and nothing else.'\n"
        "```\n\n"
        "Response (excerpt, full JSON had session_id, uuid, etc.):\n\n"
        "```json\n"
        "{\"type\":\"result\",\"subtype\":\"success\","
        "\"is_error\":false,\"duration_ms\":9621,"
        "\"result\":\"OK\",\"stop_reason\":\"end_turn\","
        "\"total_cost_usd\":0.01367,"
        "\"usage\":{\"input_tokens\":1819,\"output_tokens\":28},"
        "\"modelUsage\":{\"mimo-v2.5-pro\":"
        "{\"inputTokens\":2129,\"outputTokens\":121,"
        "\"costUSD\":0.01367,\"contextWindow\":200000}}}\n"
        "```\n\n"
        "Through the harness adapter (subprocess wrapping the same command):\n"
        "  success=True (8.1s)\n"
        "  text='OK'\n"
        "  tokens_in=1847  tokens_out=22\n"
        "  cost_usd=$0.0098  (PROVIDER-REPORTED, not estimate)\n"
        "  wire UA: claude/2.1.150 (legitimate, on Xiaomi allowlist)\n"
    )

    # Pattern A vs Pattern B trade-off context
    parts.append(
        "\n\n=== Pattern A vs Pattern B context ===\n\n"
        "The framework today uses direct httpx for all engine "
        "dispatches.  After the operator's Kimi Token Plan account was "
        "terminated 2026-05-25 for User-Agent spoofing "
        "(claude-code/0.1.0 forged identity), the team explored two "
        "alternatives:\n\n"
        "**Pattern A - Refuse + Recommend**: harness detects "
        "TOS-strict providers and refuses to dispatch with a forged "
        "UA.  Instead, it recommends the operator route through "
        "Claude Code interactively, or use a TOS-compliant alternative "
        "engine (DeepSeek PAYG, Qwen PAYG).\n\n"
        "**Pattern B - Subprocess via Claude Code CLI** (this proposal): "
        "the harness shells out to the operator's locally-installed "
        "Claude Code binary, redirected at the provider's Anthropic-"
        "compatible endpoint via ANTHROPIC_BASE_URL.  The wire-level "
        "HTTP request carries Claude Code's legitimate "
        "claude/<version> UA, which is on the provider's allowlist.  "
        "No spoofing; TOS-compliant.\n\n"
        "**Live smoke test for Pattern B has passed** (see prior "
        "section).  Architecture extended to MiMo Token Plan, MiMo "
        "PAYG, Kimi-via-CC (ready for re-subscription), Qwen, GLM, "
        "DeepSeek.\n\n"
        "**Trade-offs vs direct-httpx**:\n"
        "- +2-5s subprocess spawn overhead per dispatch\n"
        "- Provider-reported cost captured (replaces estimate)\n"
        "- Subscription quota burns when applicable (vs PAYG meter)\n"
        "- Concurrent dispatch is process-pool-bound, not connection-bound\n"
        "- DeepSeek's Anthropic-compat layer drops image / document / "
        "MCP content types (text + tool use survive)\n"
    )

    return "".join(parts)


PROMPT_TEMPLATE = """You are evaluating an architectural decision for
xaxiu-harness, a multi-engine LLM dispatch framework.  Your role is
**independent technical evaluator** - neither advocate nor adversary.
Do not validate or invalidate the design; examine it.

## Your lens this round

{lens_intro}

## Source pack

{source}

---

## Your task

Write a Markdown response with these EXACT sections.  Be precise.
Cite specific lines / functions / scenarios when you flag something.
No hedging language ("might", "could potentially") - make a claim and
defend it.

### 1. Summary stance (2-4 sentences)

What is the headline observation your lens reveals?  State it without
hedging.

### 2. Concrete concerns (ranked by severity)

For each: name the concern, cite the specific code / pattern / context
that exhibits it, explain why it matters, estimate the failure rate
(common / occasional / rare / theoretical).

### 3. Concrete strengths

Where does the design actually deliver on its claim?  Cite specifics.
This is for calibration - a critic who finds nothing good is unreliable.

### 4. Edge cases the design doesn't yet address

Things that aren't necessarily broken today but will break under
specific future conditions.  Name the condition + the breakage.

### 5. Comparison to alternatives

How does this design compare to (a) direct-httpx with truthful UA
(today's pattern, denied at gates but TOS-clean), (b) operator
manually running Claude Code interactively (no harness involvement),
(c) a pattern not yet proposed that your lens reveals?

### 6. One concrete change you'd recommend

If we ship this in the next 24 hours, what would you change?  Be
specific about the file / function / behavior.

### 7. Confidence in your evaluation (0.0-1.0)

One number + one sentence on what would shift it.

### 8. What your lens systematically misses

Acknowledge the blindspot.  One sentence.

---

Output Markdown.  Be direct.  Don't flatter the design and don't
strawman it.  If you can't find concerns, say so - but examine
carefully first.
"""


def _dispatch(engine: str, model: str, lens_id: str,
              lens_intro: str, source: str) -> dict:
    started = time.monotonic()
    out_path = OUT_DIR / f"{engine}_{lens_id}.md"
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        out_path.write_text(
            f"# {engine}/{lens_id} engine_init_failed\n\n{exc}",
            encoding="utf-8",
        )
        return {"engine": engine, "lens": lens_id, "ok": False,
                "error": str(exc),
                "elapsed_s": time.monotonic() - started}
    prompt = PROMPT_TEMPLATE.format(lens_intro=lens_intro, source=source)
    try:
        resp = eng.dispatch(prompt, model, {"max_tokens": 6000})
    except Exception as exc:
        out_path.write_text(
            f"# {engine}/{lens_id} dispatch_exception\n\n{exc}",
            encoding="utf-8",
        )
        return {"engine": engine, "lens": lens_id, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        out_path.write_text(
            f"# {engine}/{lens_id} engine_returned_empty\n\n{resp.error}",
            encoding="utf-8",
        )
        return {"engine": engine, "lens": lens_id, "ok": False,
                "error": resp.error or "(empty)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"engine": engine, "lens": lens_id, "ok": True,
            "elapsed_s": elapsed, "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out, "cost_usd": resp.cost_usd}


def _retry_one(*args, attempts: int = 2) -> dict:
    last = None
    for n in range(attempts):
        r = _dispatch(*args)
        if r["ok"]:
            return r
        last = r
        time.sleep(0.5)
    return last or {"ok": False, "error": "all retries exhausted"}


def main() -> int:
    source = _load_source()
    print(f"[pattern-b-panel] source: {len(source)} chars")
    print(f"[pattern-b-panel] firing 4 dispatches "
          f"(2 lenses x 2 engines) in parallel...")

    engines = [
        ("deepseek", "deepseek-v4-flash"),
        ("mimo", "mimo-v2.5-pro"),
    ]
    matrix: list[tuple[str, str, str, str]] = []
    for eng, model in engines:
        for lens_id, lens_intro in LENSES:
            matrix.append((eng, model, lens_id, lens_intro))

    started = time.monotonic()
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_retry_one, eng, mdl, lid, intro, source): (eng, lid)
            for eng, mdl, lid, intro in matrix
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"out={r.get('tokens_out', '-')}"
                     if r["ok"]
                     else (r.get("error") or "")[:80])
            print(f"[pattern-b-panel] {flag:<5} "
                  f"{r['engine']:<10} {r['lens']:<28} {extra}")
            results.append(r)
    elapsed = time.monotonic() - started
    ok_count = sum(1 for r in results if r["ok"])
    print(f"\n[pattern-b-panel] {ok_count}/{len(results)} complete "
          f"in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
