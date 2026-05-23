"""Independent benchmark: MiMo Standard vs MiMo Pro vs Kimi K2.6 vs DeepSeek V4 Flash.

Dispatches the same prompt set to all four engines in parallel, captures
latency + token count + response excerpt, and writes a structured JSON
report.  Run-once script — for periodic comparison, register via
Task Scheduler.

Usage:
    python -X utf8 scripts/bench_mimo_vs_kimi_deepseek.py
    # or with a custom prompt file
    python -X utf8 scripts/bench_mimo_vs_kimi_deepseek.py --prompts custom.json

Output:
    coord/benchmarks/mimo_vs_kimi_deepseek_<utc_iso>.json

Honours the same env contract as the harness — KIMI_API_KEY,
DEEPSEEK_API_KEY, MIMO_API_KEY (tp- key auto-routes to Token Plan).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# Make the harness package importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


# ---------------------------------------------------------------------------
# Default prompt suite — small, fast, varied
# ---------------------------------------------------------------------------

DEFAULT_PROMPTS: list[dict] = [
    {
        "id": "p1_simple_text",
        "category": "simple_text",
        "prompt": (
            "In exactly two sentences, explain the difference between a "
            "Python list and a Python tuple."
        ),
    },
    {
        "id": "p2_code_gen",
        "category": "code_generation",
        "prompt": (
            "Write a Python function `is_palindrome(s: str) -> bool` that "
            "returns True if `s` reads the same forwards and backwards "
            "(case-insensitive, ignoring non-alphanumeric characters). "
            "Include three example calls in a docstring.  Output only "
            "the function — no prose."
        ),
    },
    {
        "id": "p3_reasoning",
        "category": "reasoning",
        "prompt": (
            "A train leaves Station A at 9:00 going 60 mph toward Station B, "
            "which is 180 miles away.  Another train leaves Station B at "
            "10:30 going 80 mph toward Station A.  At what clock time do "
            "they meet?  Show your reasoning in 5 lines max."
        ),
    },
    {
        "id": "p4_structured",
        "category": "structured_output",
        "prompt": (
            "Output a JSON object describing the planets Mercury, Venus, "
            "Earth, and Mars.  Each value should be an object with keys "
            "`order` (int), `moons` (int), and `atmosphere` (1-word string). "
            "Output only the JSON, no markdown fence."
        ),
    },
    {
        "id": "p5_long_context_seed",
        "category": "agentic_summary",
        "prompt": (
            "You are reviewing a pull request that adds 800 lines to a "
            "Python web service.  The change introduces a new `/v2/users` "
            "endpoint with pagination.  In bullet-point form, list the "
            "five most important things you would check during review.  "
            "Be concrete, not generic."
        ),
    },
]


# Engine + model identifiers we benchmark.  All targets must be resolvable
# via harness.engines.concrete.get_engine().
ENGINE_TARGETS: list[tuple[str, str, str]] = [
    # (engine_name, model, label_for_report)
    ("kimi",     "kimi-for-coding",  "kimi-k2.6"),
    ("deepseek", "deepseek-v4-flash", "deepseek-flash"),
    ("mimo",     "mimo-v2.5",         "mimo-standard"),
    ("mimo",     "mimo-v2.5-pro",     "mimo-pro"),
]


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    prompt_id: str
    engine: str
    model: str
    label: str
    success: bool
    latency_ms: int
    response_len_chars: int
    response_excerpt: str  # first 240 chars
    error: str | None


# ---------------------------------------------------------------------------
# Dispatch one (engine, prompt) cell
# ---------------------------------------------------------------------------

def _dispatch_one(prompt_id: str, prompt: str,
                  engine_name: str, model: str, label: str) -> RunResult:
    try:
        engine = get_engine(engine_name, prefer_dpapi=False)
    except RuntimeError as exc:
        return RunResult(
            prompt_id=prompt_id, engine=engine_name, model=model, label=label,
            success=False, latency_ms=0, response_len_chars=0,
            response_excerpt="", error=f"engine_init_failed: {exc}",
        )

    started = time.monotonic()
    try:
        # W5-W 2026-05-23: don't cap max_tokens for unlimited-subscription
        # engines; engine defaults apply (Kimi 200k, MiMo 131k, DS 32k).
        resp = engine.dispatch(prompt, model, {})
    except Exception as exc:
        latency = int((time.monotonic() - started) * 1000)
        return RunResult(
            prompt_id=prompt_id, engine=engine_name, model=model, label=label,
            success=False, latency_ms=latency, response_len_chars=0,
            response_excerpt="", error=f"dispatch_exc: {exc}",
        )

    text = resp.text or ""
    return RunResult(
        prompt_id=prompt_id, engine=engine_name, model=model, label=label,
        success=bool(resp.success),
        latency_ms=int(resp.latency_ms),
        response_len_chars=len(text),
        response_excerpt=text[:240],
        error=resp.error,
    )


# ---------------------------------------------------------------------------
# Orchestrate full grid in parallel
# ---------------------------------------------------------------------------

def run_grid(prompts: list[dict], targets: list[tuple[str, str, str]]) -> list[RunResult]:
    futures: list[concurrent.futures.Future[RunResult]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for p in prompts:
            for engine_name, model, label in targets:
                fut = pool.submit(
                    _dispatch_one,
                    p["id"], p["prompt"], engine_name, model, label,
                )
                futures.append(fut)
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    return results


# ---------------------------------------------------------------------------
# Aggregate + write report
# ---------------------------------------------------------------------------

def summarise(results: list[RunResult]) -> dict:
    by_label: dict[str, dict] = {}
    for r in results:
        bucket = by_label.setdefault(r.label, {
            "engine": r.engine, "model": r.model,
            "runs": 0, "successes": 0, "failures": 0,
            "total_latency_ms": 0,
            "total_response_chars": 0,
            "errors": [],
        })
        bucket["runs"] += 1
        if r.success:
            bucket["successes"] += 1
            bucket["total_latency_ms"] += r.latency_ms
            bucket["total_response_chars"] += r.response_len_chars
        else:
            bucket["failures"] += 1
            if r.error:
                bucket["errors"].append({"prompt": r.prompt_id, "error": r.error})
    # Compute averages where applicable
    for label, b in by_label.items():
        if b["successes"]:
            b["avg_latency_ms"] = round(b["total_latency_ms"] / b["successes"], 1)
            b["avg_response_chars"] = round(b["total_response_chars"] / b["successes"], 1)
        else:
            b["avg_latency_ms"] = None
            b["avg_response_chars"] = None
    return by_label


def write_report(results: list[RunResult], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"mimo_vs_kimi_deepseek_{stamp}.json"
    payload = {
        "schema_version": 1,
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summarise(results),
        "results": [asdict(r) for r in results],
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", type=Path, default=None,
                        help="JSON file with prompt set (default: built-in)")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("coord") / "benchmarks")
    args = parser.parse_args()

    if args.prompts:
        prompts = json.loads(args.prompts.read_text(encoding="utf-8"))
    else:
        prompts = DEFAULT_PROMPTS

    print(f"[bench] starting grid: {len(prompts)} prompts x {len(ENGINE_TARGETS)} engines "
          f"= {len(prompts) * len(ENGINE_TARGETS)} dispatches", flush=True)
    started = time.monotonic()
    results = run_grid(prompts, ENGINE_TARGETS)
    elapsed = time.monotonic() - started
    out_path = write_report(results, args.out_dir)
    print(f"[bench] wrote {out_path}  ({elapsed:.1f}s wall)", flush=True)

    # One-line summary table to stdout
    summary = summarise(results)
    print()
    print(f"{'label':22s} {'ok/N':>7s} {'avg_ms':>9s} {'avg_chars':>10s}")
    for label, b in sorted(summary.items()):
        ok = f"{b['successes']}/{b['runs']}"
        ms = f"{b['avg_latency_ms']}" if b['avg_latency_ms'] is not None else "-"
        ch = f"{b['avg_response_chars']}" if b['avg_response_chars'] is not None else "-"
        print(f"{label:22s} {ok:>7s} {ms:>9s} {ch:>10s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
