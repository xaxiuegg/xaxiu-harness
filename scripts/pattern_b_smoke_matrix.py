"""Pattern B intensive smoke-test matrix.

Operator request 2026-05-26: test all categories intensively for
claude-kimi / claude-mimo / claude-deepseek.

5 categories x 3 engines = 15 dispatches.  Each prompt is small (<300
chars) and capped at $0.10 to bound total cost.  Results written to
coord/reviews/pattern-b-smoke-matrix/RESULTS.md.
"""
from __future__ import annotations

import concurrent.futures as _cf
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO / "coord" / "reviews" / "pattern-b-smoke-matrix"
OUT_DIR.mkdir(parents=True, exist_ok=True)


ENGINES = ["kimi-via-claude", "mimo-via-claude", "deepseek-via-claude"]


LONG_INPUT = (
    "Below is a Python function with a subtle off-by-one bug. "
    "Identify the bug in one sentence:\n\n"
    "def fenwick_update(tree, i, val):\n"
    "    while i < len(tree):\n"
    "        tree[i] += val\n"
    "        i += i & -i\n"
    "    return tree\n\n"
    "def fenwick_query(tree, i):\n"
    "    s = 0\n"
    "    while i > 0:\n"
    "        s += tree[i]\n"
    "        i -= i & -i\n"
    "    return s\n\n"
    "# Caller code (the bug is here, not in the functions above)\n"
    "n = 10\n"
    "tree = [0] * n  # <-- this is the bug - index by 1 not 0\n"
    "for i in range(1, n+1):\n"
    "    fenwick_update(tree, i, i)\n"
    "print(fenwick_query(tree, 5))\n\n"
    "Background context that should NOT affect the answer (padding to "
    "test long-context preservation): "
    + ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, "
       "sed do eiusmod tempor incididunt ut labore et dolore magna "
       "aliqua. " * 30)
    + "\n\nIdentify the bug in ONE sentence.  No code."
)


CATEGORIES: list[tuple[str, str]] = [
    ("trivial",
     "Reply with the single word OK and nothing else."),
    ("code",
     "Write a Python function is_palindrome(s) that returns True if "
     "string s reads the same forwards and backwards. Just the "
     "function. No explanation."),
    ("reasoning",
     "Why is mergesort O(n log n)? Answer in one sentence, no code."),
    ("long_context",
     LONG_INPUT),
    ("multimodal_probe",
     "Look at this diagram ![system architecture](architecture.png) "
     "and describe what it shows. If no image is accessible, say so "
     "plainly."),
]


def _dispatch_one(engine_name: str, category: str, prompt: str) -> dict:
    started = time.monotonic()
    try:
        eng = get_engine(engine_name)
    except RuntimeError as exc:
        return {
            "engine": engine_name, "category": category, "ok": False,
            "elapsed_s": 0.0, "tokens_in": 0, "tokens_out": 0,
            "cost_usd": 0.0, "output_excerpt": "",
            "error": f"get_engine failed: {exc}",
        }
    try:
        resp = eng.dispatch(
            prompt, "",
            {"max_budget_usd": 0.10, "timeout_s": 90},
        )
    except Exception as exc:
        return {
            "engine": engine_name, "category": category, "ok": False,
            "elapsed_s": time.monotonic() - started,
            "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
            "output_excerpt": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    elapsed = time.monotonic() - started
    excerpt = (resp.text or "")[:200].replace("\n", " ").strip()
    return {
        "engine": engine_name, "category": category,
        "ok": bool(resp.success),
        "elapsed_s": elapsed,
        "tokens_in": int(resp.tokens_in or 0),
        "tokens_out": int(resp.tokens_out or 0),
        "cost_usd": float(resp.cost_usd or 0.0),
        "output_excerpt": excerpt,
        "error": (resp.error or "") if not resp.success else "",
    }


def main() -> int:
    print(f"[smoke-matrix] firing {len(ENGINES) * len(CATEGORIES)} "
          f"dispatches (3 engines x 5 categories) in parallel...")
    started = time.monotonic()

    matrix: list[tuple[str, str, str]] = [
        (eng, cat_name, prompt)
        for eng in ENGINES
        for cat_name, prompt in CATEGORIES
    ]

    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        future_to_key = {
            pool.submit(_dispatch_one, eng, cat, prompt): (eng, cat)
            for eng, cat, prompt in matrix
        }
        for fut in _cf.as_completed(future_to_key):
            r = fut.result()
            results.append(r)
            flag = "OK" if r["ok"] else "FAIL"
            print(f"  {flag:<4} {r['engine']:<22} {r['category']:<18} "
                  f"{r['elapsed_s']:>6.1f}s "
                  f"in={r['tokens_in']:>5} out={r['tokens_out']:>4} "
                  f"${r['cost_usd']:.4f}")

    elapsed = time.monotonic() - started
    ok_count = sum(1 for r in results if r["ok"])
    total_cost = sum(r["cost_usd"] for r in results)
    print(f"\n[smoke-matrix] {ok_count}/{len(results)} OK in "
          f"{elapsed:.0f}s, total cost ${total_cost:.4f}")

    sort_key = lambda r: (
        ENGINES.index(r["engine"]),
        [c for c, _ in CATEGORIES].index(r["category"]),
    )
    results.sort(key=sort_key)

    (OUT_DIR / "raw_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _write_markdown_report(results, elapsed, ok_count, total_cost)
    return 0


def _write_markdown_report(
    results: list[dict],
    elapsed: float, ok_count: int, total_cost: float,
) -> None:
    lines: list[str] = [
        "# Pattern B intensive smoke-test matrix - RESULTS",
        "",
        "**Date**: 2026-05-26",
        f"**Total dispatches**: {len(results)} ({len(ENGINES)} engines x "
        f"{len(CATEGORIES)} categories)",
        f"**Success rate**: {ok_count}/{len(results)} "
        f"({ok_count/len(results)*100:.0f}%)",
        f"**Elapsed**: {elapsed:.0f}s wall-clock",
        f"**Total cost**: ${total_cost:.4f}",
        "",
        "## Per-engine summary",
        "",
        "| Engine | Categories OK | Total tokens out | Total cost | Avg latency |",
        "|---|---|---|---|---|",
    ]
    for eng in ENGINES:
        eng_rows = [r for r in results if r["engine"] == eng]
        ok = sum(1 for r in eng_rows if r["ok"])
        toks = sum(r["tokens_out"] for r in eng_rows)
        cost = sum(r["cost_usd"] for r in eng_rows)
        avg_lat = (
            sum(r["elapsed_s"] for r in eng_rows) / max(1, len(eng_rows))
        )
        lines.append(
            f"| `{eng}` | {ok}/{len(eng_rows)} | {toks} | ${cost:.4f} | "
            f"{avg_lat:.1f}s |"
        )

    lines.extend([
        "",
        "## Full matrix",
        "",
        "| Engine | Category | OK | Latency | In | Out | Cost | Output excerpt |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for r in results:
        excerpt = r["output_excerpt"][:120].replace("|", "\\|")
        ok_emoji = "ok" if r["ok"] else "FAIL"
        lines.append(
            f"| `{r['engine']}` | {r['category']} | {ok_emoji} | "
            f"{r['elapsed_s']:.1f}s | "
            f"{r['tokens_in']} | {r['tokens_out']} | "
            f"${r['cost_usd']:.4f} | {excerpt} |"
        )

    failures = [r for r in results if not r["ok"]]
    if failures:
        lines.extend(["", "## Failures (full error text)", ""])
        for r in failures:
            lines.append(f"### {r['engine']} / {r['category']}")
            lines.append("")
            lines.append("```")
            lines.append(r["error"])
            lines.append("```")
            lines.append("")

    lines.extend(["", "## Per-category outputs (compare engine answers)", ""])
    for cat_name, _prompt in CATEGORIES:
        lines.append(f"### {cat_name}")
        lines.append("")
        for eng in ENGINES:
            row = next(
                (r for r in results
                 if r["engine"] == eng and r["category"] == cat_name),
                None,
            )
            if row is None:
                continue
            if row["ok"]:
                lines.append(f"**{eng}** ({row['elapsed_s']:.1f}s, "
                              f"${row['cost_usd']:.4f}):")
            else:
                lines.append(f"**{eng}** (FAILED):")
            lines.append("")
            if row["ok"]:
                lines.append("```")
                lines.append(row["output_excerpt"])
                lines.append("```")
            else:
                lines.append("```")
                lines.append(row["error"][:300])
                lines.append("```")
            lines.append("")

    (OUT_DIR / "RESULTS.md").write_text(
        "\n".join(lines), encoding="utf-8",
    )
    print(f"[smoke-matrix] wrote {OUT_DIR / 'RESULTS.md'}")


if __name__ == "__main__":
    sys.exit(main())
