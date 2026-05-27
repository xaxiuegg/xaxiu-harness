"""W14-MIMO-PRODUCTION-VALIDATION 2026-05-26: production-class
quality + robustness validation for MiMo-via-claude.

Audit-panel pushback: MiMo's promotion to cost-class primary is
backed by smoke-matrix data, not production-class evidence.  This
script generates that evidence by:

  Phase 1: Diverse prompt corpus (10 prompts × 3 engines = 30
           dispatches) covering categories the audit-panel
           specifically called out as untested by smoke runs.

  Phase 2: Programmatic scoring — what we can measure without
           operator judgement: success/fail, latency, tokens,
           cost, output-non-empty, tool-call XML markup
           detection, JSON-validity on json prompts, word-count
           compliance.

  Phase 3: Concurrency stress — fire 10 simultaneous MiMo
           dispatches, observe throttling / fallback / cost.

  Phase 4: Synthesis verdict — does MiMo hold up vs DeepSeek-flash
           + Kimi on realistic prompts?

Output: coord/reviews/mimo-production-validation-2026-05-26/
  - corpus_results.json    (all 30 dispatches, raw + scored)
  - stress_results.json    (10 concurrent MiMo dispatches)
  - SYNTHESIS.md           (operator-facing verdict)

Cost estimate: ~$1.50 total.
"""
import concurrent.futures as _cf
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine

OUT_DIR = (
    REPO / "coord" / "reviews" / "mimo-production-validation-2026-05-26"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)


ENGINES = [
    ("mimo-via-claude", ""),
    ("deepseek-via-claude", "deepseek-v4-flash"),
    ("kimi-via-claude", ""),
]


# ===========================================================================
# CORPUS — 10 prompts covering categories the audit panel said the smoke
# matrix didn't characterize.  Each entry has scoring metadata.
# ===========================================================================


CORPUS: list[dict] = [
    {
        "id": "code_function",
        "category": "code-gen",
        "prompt": (
            "Write a Python function `fibonacci(n)` that returns the "
            "nth Fibonacci number.  Use iteration, not recursion.  "
            "Just the function body.  No explanation."
        ),
        "checks": [
            ("non_empty", None),
            ("contains", "def fibonacci"),
            ("contains", "return"),
        ],
    },
    {
        "id": "reasoning_short",
        "category": "reasoning",
        "prompt": (
            "Why does quicksort have O(n²) worst-case complexity?  "
            "Answer in exactly one sentence.  No code, no explanation "
            "beyond the sentence."
        ),
        "checks": [
            ("non_empty", None),
            ("word_count_at_most", 50),
        ],
    },
    {
        "id": "structured_json",
        "category": "structured-output",
        "prompt": (
            "Return ONLY a valid JSON object (no markdown fence, no "
            "prose) with these fields: language: 'python', "
            "complexity: 'O(log n)', algorithm: 'binary_search'.  "
            "Output the JSON object on one line."
        ),
        "checks": [
            ("non_empty", None),
            ("valid_json", None),
            ("json_has_keys", ["language", "complexity", "algorithm"]),
        ],
    },
    {
        "id": "long_context_bugfind",
        "category": "long-context",
        "prompt": (
            "Below is a Python function with a subtle off-by-one bug.  "
            "Identify the bug in one sentence:\n\n"
            "def reverse_list(items):\n"
            "    n = len(items)\n"
            "    for i in range(n // 2 + 1):\n"
            "        items[i], items[n - 1 - i] = items[n - 1 - i], items[i]\n"
            "    return items\n\n"
            + ("Padding context to test long-context preservation: "
               "Lorem ipsum dolor sit amet, consectetur adipiscing "
               "elit, sed do eiusmod tempor incididunt ut labore et "
               "dolore magna aliqua. " * 30)
            + "\n\nIdentify the bug in ONE sentence.  No code."
        ),
        "checks": [
            ("non_empty", None),
            ("contains_any", ["n // 2 + 1", "+1", "off-by-one",
                              "extra iteration", "swap back"]),
        ],
    },
    {
        "id": "multi_turn_instruction",
        "category": "multi-step-instruction",
        "prompt": (
            "Do exactly these three things in this order, labeled "
            "1/2/3:\n"
            "1) State the capital of France.\n"
            "2) Convert 100 USD to EUR (assume rate 0.92).\n"
            "3) List the colors of the rainbow in order.\n"
            "Do NOT add introduction or summary."
        ),
        "checks": [
            ("non_empty", None),
            ("contains", "Paris"),
            ("contains_any", ["92", "92.00"]),  # 100*0.92 = 92
            ("contains_any", ["red", "Red"]),
        ],
    },
    {
        "id": "concise_constraint",
        "category": "length-compliance",
        "prompt": (
            "Explain the difference between TCP and UDP.  Maximum 25 words."
        ),
        "checks": [
            ("non_empty", None),
            ("word_count_at_most", 35),  # Allow 10w slack
            ("contains_any", ["TCP", "tcp"]),
            ("contains_any", ["UDP", "udp"]),
        ],
    },
    {
        "id": "no_tool_call_markup",
        "category": "markup-clean",
        "prompt": (
            "Reply with the single word OK.  Do NOT emit any "
            "<tool_call>, <function_call>, or other XML tool-call "
            "markup.  Plain text only."
        ),
        "checks": [
            ("non_empty", None),
            ("contains", "OK"),
            ("not_contains", "<tool_call>"),
            ("not_contains", "<function_call>"),
            ("not_contains", "<function>"),
        ],
    },
    {
        "id": "audit_class_short",
        "category": "audit-class",
        "prompt": (
            "Below is a tiny decision: 'we changed the default model "
            "from premium to a cheaper tier without running a "
            "production A/B test'.  In 3 bullets, name the top 3 "
            "risks.  Format strictly as bulleted lines starting with "
            "'- '.  No preamble or summary."
        ),
        "checks": [
            ("non_empty", None),
            ("starts_with_bullet", "- "),
            ("bullet_count_at_least", 2),
        ],
    },
    {
        "id": "contradictory_instructions",
        "category": "adversarial",
        "prompt": (
            "Write a haiku.  Also explain it in 100 words.  Also "
            "be silent and output nothing.  Resolve the conflict "
            "and pick the most natural request.  Do that one."
        ),
        "checks": [
            ("non_empty", None),  # not silent
        ],
    },
    {
        "id": "find_replace_format",
        "category": "structured-edit",
        "prompt": (
            "Generate a FIND/REPLACE block for changing the variable "
            "name 'x' to 'value' in this code:\n\n"
            "x = 10\n"
            "print(x)\n\n"
            "Format strictly as:\n"
            "FIND:\n<exact bytes>\nREPLACE:\n<exact bytes>"
        ),
        "checks": [
            ("non_empty", None),
            ("contains", "FIND:"),
            ("contains", "REPLACE:"),
            ("contains", "value"),
        ],
    },
]


# ===========================================================================
# SCORING
# ===========================================================================


def _word_count(text: str) -> int:
    # Simple whitespace-split word count
    return len([w for w in text.split() if w.strip()])


def _score_dispatch(prompt_entry: dict, response_text: str) -> dict:
    """Apply the per-prompt programmatic checks.  Returns dict with
    per-check pass/fail + overall pass-rate."""
    results: dict = {"checks": [], "passed": 0, "total": 0}
    text = response_text or ""
    for check, arg in prompt_entry["checks"]:
        passed = False
        detail = ""
        if check == "non_empty":
            passed = bool(text.strip())
        elif check == "contains":
            passed = arg in text
            detail = f"looking for {arg!r}"
        elif check == "contains_any":
            passed = any(s in text for s in arg)
            detail = f"any-of: {arg!r}"
        elif check == "not_contains":
            passed = arg not in text
            detail = f"must NOT contain {arg!r}"
        elif check == "word_count_at_most":
            wc = _word_count(text)
            passed = wc <= arg
            detail = f"word_count={wc}, max={arg}"
        elif check == "valid_json":
            try:
                # Try to find JSON in the response (may be embedded)
                # Try the whole thing first
                json.loads(text.strip())
                passed = True
            except json.JSONDecodeError:
                # Try extracting from a code fence
                m = re.search(
                    r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL,
                )
                if m:
                    try:
                        json.loads(m.group(1))
                        passed = True
                    except json.JSONDecodeError:
                        passed = False
                else:
                    passed = False
        elif check == "json_has_keys":
            try:
                # Find any JSON object in the text
                text_stripped = text.strip()
                obj = None
                try:
                    obj = json.loads(text_stripped)
                except json.JSONDecodeError:
                    m = re.search(
                        r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
                        text, re.DOTALL,
                    )
                    if m:
                        try:
                            obj = json.loads(m.group(0))
                        except json.JSONDecodeError:
                            pass
                if obj is not None:
                    passed = all(k in obj for k in arg)
                    detail = f"required keys: {arg}, found: {list(obj)}"
            except Exception:
                passed = False
        elif check == "starts_with_bullet":
            lines = [
                line for line in text.split("\n")
                if line.strip()
            ]
            passed = any(line.startswith(arg) for line in lines)
            detail = f"prefix {arg!r}"
        elif check == "bullet_count_at_least":
            bullet_lines = [
                line for line in text.split("\n")
                if line.strip().startswith(("-", "*", "•"))
            ]
            passed = len(bullet_lines) >= arg
            detail = f"found {len(bullet_lines)} bullets, need >= {arg}"
        results["checks"].append({
            "check": check, "arg": arg,
            "passed": passed, "detail": detail,
        })
        results["total"] += 1
        if passed:
            results["passed"] += 1
    results["pass_rate"] = (
        results["passed"] / max(1, results["total"])
    )
    return results


# ===========================================================================
# DISPATCH
# ===========================================================================


def _dispatch(combo: tuple[str, str], prompt_entry: dict) -> dict:
    engine_name, model = combo
    started = time.monotonic()
    eng = get_engine(engine_name)
    extra = {"max_budget_usd": 0.20, "timeout_s": 180}
    if model:
        extra["model"] = model
    try:
        resp = eng.dispatch(prompt_entry["prompt"], model, extra)
    except Exception as exc:
        return {
            "engine": engine_name, "model": model,
            "prompt_id": prompt_entry["id"],
            "ok": False,
            "elapsed_s": time.monotonic() - started,
            "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
            "text": "",
            "error": f"{type(exc).__name__}: {exc}",
            "score": {"checks": [], "passed": 0, "total": 0,
                      "pass_rate": 0.0},
        }
    elapsed = time.monotonic() - started
    text = resp.text or ""
    return {
        "engine": engine_name,
        "model": model,
        "prompt_id": prompt_entry["id"],
        "category": prompt_entry["category"],
        "ok": bool(resp.success),
        "elapsed_s": elapsed,
        "tokens_in": int(resp.tokens_in or 0),
        "tokens_out": int(resp.tokens_out or 0),
        "cost_usd": float(resp.cost_usd or 0.0),
        "text": text,
        "text_excerpt": text[:300].replace("\n", " "),
        "error": (resp.error or "") if not resp.success else "",
        "score": _score_dispatch(prompt_entry, text),
    }


# ===========================================================================
# PHASE 1+2: corpus + scoring
# ===========================================================================


def phase_corpus() -> list[dict]:
    print(f"[mimo-validation] Phase 1+2: corpus dispatch + scoring")
    print(f"  {len(CORPUS)} prompts x {len(ENGINES)} engines = "
          f"{len(CORPUS) * len(ENGINES)} dispatches")
    started = time.monotonic()
    work: list[tuple[tuple[str, str], dict]] = [
        (eng, p) for eng in ENGINES for p in CORPUS
    ]
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=6) as pool:
        for r in pool.map(lambda w: _dispatch(*w), work):
            results.append(r)
            flag = "OK" if r["ok"] else "FAIL"
            score = r["score"]
            print(f"  {flag:<4} {r['engine']:<22} {r['prompt_id']:<26} "
                  f"{r['elapsed_s']:>5.1f}s "
                  f"score={score['passed']}/{score['total']} "
                  f"${r['cost_usd']:.4f}")
    elapsed = time.monotonic() - started
    total = sum(r["cost_usd"] for r in results)
    print(f"  -> done in {elapsed:.0f}s, total cost ${total:.4f}")
    return results


# ===========================================================================
# PHASE 3: concurrency stress on MiMo
# ===========================================================================


def phase_concurrency_stress() -> list[dict]:
    print(f"[mimo-validation] Phase 3: concurrency stress on MiMo")
    n = 10
    print(f"  {n} simultaneous MiMo dispatches of trivial prompt")
    started = time.monotonic()
    stress_prompt = {
        "id": "concurrency_probe",
        "category": "stress",
        "prompt": "Reply with the word OK and nothing else.",
        "checks": [("non_empty", None), ("contains", "OK")],
    }
    work = [(("mimo-via-claude", ""), stress_prompt) for _ in range(n)]
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=n) as pool:
        for r in pool.map(lambda w: _dispatch(*w), work):
            results.append(r)
            flag = "OK" if r["ok"] else "FAIL"
            print(f"  {flag:<4} mimo-via-claude  "
                  f"{r['elapsed_s']:>5.1f}s "
                  f"${r['cost_usd']:.4f} "
                  f"{r['text_excerpt'][:30]}")
    elapsed = time.monotonic() - started
    ok = sum(1 for r in results if r["ok"])
    p95 = sorted(r["elapsed_s"] for r in results)[int(0.95 * n)] \
        if n > 1 else results[0]["elapsed_s"]
    p50 = sorted(r["elapsed_s"] for r in results)[n // 2]
    print(f"  -> {ok}/{n} OK, wall {elapsed:.0f}s, "
          f"p50 {p50:.1f}s, p95 {p95:.1f}s")
    return results


# ===========================================================================
# SYNTHESIS
# ===========================================================================


def synthesize(
    corpus_results: list[dict],
    stress_results: list[dict],
) -> str:
    lines: list[str] = [
        "# W14-MIMO-PRODUCTION-VALIDATION — synthesis",
        "",
        "**Date**: 2026-05-26",
        "**Method**: 10 prompts × 3 engines + 10-way concurrent "
        "MiMo stress.",
        "",
        "## Per-engine summary (corpus phase)",
        "",
        "| Engine | OK / 10 | Score / 30 checks | Total cost | "
        "Avg latency | Avg tokens out |",
        "|---|---|---|---|---|---|",
    ]
    by_engine: dict[str, list[dict]] = {}
    for r in corpus_results:
        by_engine.setdefault(r["engine"], []).append(r)
    for eng in [c[0] for c in ENGINES]:
        rows = by_engine.get(eng, [])
        ok = sum(1 for r in rows if r["ok"])
        cost = sum(r["cost_usd"] for r in rows)
        score_passed = sum(r["score"]["passed"] for r in rows)
        score_total = sum(r["score"]["total"] for r in rows)
        avg_lat = (
            sum(r["elapsed_s"] for r in rows) / max(1, len(rows))
        )
        avg_out = (
            sum(r["tokens_out"] for r in rows) / max(1, len(rows))
        )
        lines.append(
            f"| `{eng}` | {ok}/{len(rows)} | {score_passed}/"
            f"{score_total} | ${cost:.4f} | {avg_lat:.1f}s | "
            f"{avg_out:.0f} |"
        )

    lines.extend([
        "",
        "## Per-prompt comparison",
        "",
        "Score format: ✓N/M (N checks passed of M total).",
        "",
        "| Prompt | Category | mimo | deepseek-flash | kimi |",
        "|---|---|---|---|---|",
    ])
    by_id: dict[tuple[str, str], dict] = {}
    for r in corpus_results:
        by_id[(r["prompt_id"], r["engine"])] = r
    for entry in CORPUS:
        row = [entry["id"], entry["category"]]
        for eng_name, _ in ENGINES:
            r = by_id.get((entry["id"], eng_name))
            if r and r["ok"]:
                s = r["score"]
                row.append(
                    f"✓{s['passed']}/{s['total']} "
                    f"({r['elapsed_s']:.1f}s)"
                )
            else:
                row.append("FAIL")
        lines.append("| " + " | ".join(row) + " |")

    lines.extend([
        "",
        "## Concurrency stress (Phase 3)",
        "",
        f"Fired {len(stress_results)} simultaneous MiMo dispatches.",
        "",
    ])
    ok = sum(1 for r in stress_results if r["ok"])
    if stress_results:
        n = len(stress_results)
        sorted_lat = sorted(r["elapsed_s"] for r in stress_results)
        p50 = sorted_lat[n // 2]
        p95 = sorted_lat[int(0.95 * n)] if n >= 5 else sorted_lat[-1]
        max_lat = sorted_lat[-1]
        min_lat = sorted_lat[0]
        total_cost = sum(r["cost_usd"] for r in stress_results)
        any_429 = any(
            "429" in (r.get("error") or "")
            or "rate" in (r.get("error") or "").lower()
            for r in stress_results
        )
        lines.extend([
            f"- Success: {ok}/{n}",
            f"- Latency: min {min_lat:.1f}s, p50 {p50:.1f}s, "
            f"p95 {p95:.1f}s, max {max_lat:.1f}s",
            f"- Total cost: ${total_cost:.4f}",
            f"- Rate-limit / throttling observed: {'YES' if any_429 else 'no'}",
            "",
        ])

    # Failure detail
    failures = [r for r in corpus_results if not r["ok"]]
    if failures:
        lines.extend([
            "## Failures",
            "",
        ])
        for r in failures:
            lines.append(
                f"- `{r['engine']}` / `{r['prompt_id']}`: "
                f"{r['error'][:200]}"
            )
        lines.append("")

    # Markup-quirk specific check
    lines.extend([
        "## Audit-panel concerns: empirical answers",
        "",
        "**Tool-call XML markup quirk** — does MiMo emit unexecuted "
        "`<tool_call>` / `<function_call>` markup that breaks downstream parsing?",
        "",
    ])
    markup_offenders = []
    for r in corpus_results:
        text = r.get("text", "")
        if r["engine"] != "mimo-via-claude":
            continue
        if any(tag in text for tag in
               ("<tool_call>", "<function_call>", "<function>")):
            markup_offenders.append({
                "prompt_id": r["prompt_id"],
                "category": r["category"],
            })
    if markup_offenders:
        lines.append(
            f"**Markup observed in {len(markup_offenders)}/10 MiMo "
            f"responses.**  Affected prompts:"
        )
        for m in markup_offenders:
            lines.append(f"- `{m['prompt_id']}` ({m['category']})")
    else:
        lines.append(
            "**Clean: 0/10 MiMo responses contained tool-call XML "
            "markup.**  The `--tools \"\"` flag combined with our "
            "explicit 'no tool-call markup' instructions in some "
            "prompts is effective."
        )
    lines.append("")

    # Word-count compliance
    wc_failures_mimo = [
        r for r in corpus_results
        if r["engine"] == "mimo-via-claude"
        and any(
            c["check"] == "word_count_at_most" and not c["passed"]
            for c in r["score"]["checks"]
        )
    ]
    lines.extend([
        "**Word-count compliance** — does MiMo respect explicit "
        f"length caps in prompts?",
        "",
    ])
    if wc_failures_mimo:
        lines.append(
            f"**{len(wc_failures_mimo)} word-count violation(s) by MiMo:**"
        )
        for r in wc_failures_mimo:
            lines.append(f"- `{r['prompt_id']}`")
    else:
        lines.append("**Clean: MiMo respected all word-count caps.**")
    lines.append("")

    # Verdict
    lines.extend([
        "## Verdict",
        "",
    ])
    mimo_rows = by_engine.get("mimo-via-claude", [])
    flash_rows = by_engine.get("deepseek-via-claude", [])
    kimi_rows = by_engine.get("kimi-via-claude", [])

    def _score_pct(rows: list[dict]) -> float:
        tot = sum(r["score"]["total"] for r in rows)
        if tot == 0:
            return 0.0
        return sum(r["score"]["passed"] for r in rows) / tot * 100

    mimo_pct = _score_pct(mimo_rows)
    flash_pct = _score_pct(flash_rows)
    kimi_pct = _score_pct(kimi_rows)
    lines.extend([
        f"- MiMo score: {mimo_pct:.0f}%",
        f"- DeepSeek-flash score: {flash_pct:.0f}%",
        f"- Kimi score: {kimi_pct:.0f}%",
        "",
    ])

    return "\n".join(lines)


# ===========================================================================
# MAIN
# ===========================================================================


def main() -> int:
    started = time.monotonic()
    corpus = phase_corpus()
    stress = phase_concurrency_stress()

    (OUT_DIR / "corpus_results.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUT_DIR / "stress_results.json").write_text(
        json.dumps(stress, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    synthesis = synthesize(corpus, stress)
    (OUT_DIR / "SYNTHESIS.md").write_text(synthesis, encoding="utf-8")

    elapsed = time.monotonic() - started
    total_cost = (
        sum(r["cost_usd"] for r in corpus)
        + sum(r["cost_usd"] for r in stress)
    )
    print(
        f"\n[mimo-validation] DONE in {elapsed:.0f}s, "
        f"total cost ${total_cost:.4f}"
    )
    print(f"  artifacts in {OUT_DIR.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
