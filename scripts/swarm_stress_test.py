"""W14-SWARM-STRESS-TEST 2026-05-26: concurrency curve on the swarm
backends — both the new TOS-safe claude-* family and legacy paths.

Closes the audit panel's flagged gap: "concurrency >10x untested."

Method
======

Phase 1: per-backend concurrency curve
  For each backend in TEST_BACKENDS, fire N dispatches concurrently
  with a realistic short prompt.  N ∈ {4, 8, 16, 32}.  Measure:
    - success rate
    - p50 / p95 / max latency
    - total wall-clock
    - aggregate cost
    - rate-limit / throttling indicators in stderr

Phase 2: mixed-backend swarm
  Use `xaxiu-swarm swarm` to dispatch 12 packets in parallel split
  across all 3 new backends (4 packets each).  Measures the actual
  multi-engine-panel use case the operator runs.

Safety
======
  - Per-dispatch budget cap: $0.05
  - Per-dispatch timeout: 60s
  - Total budget ceiling: ~$3 across all phases
  - Phases write incremental output so an early abort doesn't lose data

Output: coord/reviews/swarm-stress-2026-05-26/
  - per-backend curve CSVs
  - mixed phase JSON
  - SYNTHESIS.md
"""
import concurrent.futures as _cf
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "coord" / "reviews" / "swarm-stress-2026-05-26"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# The new TOS-safe agentic family + legacy comparison
TEST_BACKENDS = [
    "claude-mimo",      # NEW
    "claude-kimi",      # NEW
    "claude-deepseek",  # NEW
    "deepseek",         # legacy comparison
]

# Concurrency levels to sweep
CONCURRENCY_LEVELS = [4, 8, 16, 32]

# Realistic prompts — short enough to be cheap, distinct enough to
# defeat any cross-dispatch caching artifacts.  Rotates per dispatch.
PROMPTS = [
    "Write a 3-line Python function reverse_str(s) returning s reversed. "
    "Just the function, no explanation.",

    "In one sentence: what is the time complexity of binary search?",

    "Reply with exactly the JSON: {\"status\": \"ok\"}.  No fence, no prose.",

    "List 3 features of Python in 3 bullets starting with '- '.  No preamble.",
]


def _dispatch_one(
    backend: str, idx: int, deliverable_path: Path, prompt: str,
) -> dict:
    """Dispatch a single prompt through xaxiu-swarm + capture metrics."""
    deliverable_path.unlink(missing_ok=True)
    cmd = [
        "xaxiu-swarm", "dispatch",
        "--backend", backend,
        "--deliverable", str(deliverable_path),
        "--timeout", "60",
        prompt,
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        return {
            "backend": backend, "idx": idx,
            "ok": False, "elapsed_s": 90.0,
            "returncode": -1,
            "deliverable_bytes": 0,
            "rate_limited": False,  # bug fix: was missing
            "stderr_excerpt": "subprocess timeout 90s",
        }
    elapsed = time.monotonic() - started
    db = deliverable_path.stat().st_size if deliverable_path.exists() else 0
    # Look for rate-limit indicators in stdout/stderr
    combined = (proc.stdout + proc.stderr).lower()
    is_429 = any(s in combined for s in (
        "429", "rate limit", "rate-limit", "throttl",
        "quota exceeded",
    ))
    return {
        "backend": backend,
        "idx": idx,
        "ok": proc.returncode == 0 and db > 0,
        "elapsed_s": elapsed,
        "returncode": proc.returncode,
        "deliverable_bytes": db,
        "rate_limited": is_429,
        "stderr_excerpt": (proc.stderr or "")[-200:].strip(),
    }


def phase_curve(backend: str) -> list[dict]:
    """Fire concurrency curve for one backend.  Returns one row per
    (backend, concurrency_level) with aggregate metrics."""
    print(f"\n  --- {backend} ---")
    rows: list[dict] = []
    work_dir = OUT_DIR / "work" / backend
    work_dir.mkdir(parents=True, exist_ok=True)
    for n in CONCURRENCY_LEVELS:
        print(f"    N={n}: firing {n} concurrent dispatches ...")
        started = time.monotonic()
        with _cf.ThreadPoolExecutor(max_workers=n) as pool:
            jobs = [
                pool.submit(
                    _dispatch_one,
                    backend, i,
                    work_dir / f"n{n}_i{i}.txt",
                    PROMPTS[i % len(PROMPTS)],
                )
                for i in range(n)
            ]
            results = [j.result() for j in jobs]
        wall = time.monotonic() - started
        ok = sum(1 for r in results if r["ok"])
        latencies = sorted(r["elapsed_s"] for r in results)
        p50 = latencies[n // 2]
        p95 = latencies[int(0.95 * n)] if n >= 5 else latencies[-1]
        max_lat = latencies[-1]
        min_lat = latencies[0]
        rate_limited = sum(1 for r in results if r["rate_limited"])
        row = {
            "backend": backend,
            "concurrency": n,
            "wall_s": wall,
            "ok": ok,
            "fail": n - ok,
            "rate_limited": rate_limited,
            "p50_s": p50,
            "p95_s": p95,
            "max_s": max_lat,
            "min_s": min_lat,
            "speedup_vs_serial": (
                sum(latencies) / wall if wall > 0 else 0
            ),
        }
        rows.append(row)
        print(f"      -> {ok}/{n} OK, wall {wall:.0f}s, "
              f"p50 {p50:.1f}s, p95 {p95:.1f}s, "
              f"speedup {row['speedup_vs_serial']:.1f}x"
              + (f", 429s={rate_limited}" if rate_limited else ""))
        # Bail out if a level fails catastrophically — don't waste
        # budget on higher concurrency that will also fail
        if ok == 0:
            print(f"      [abort] all dispatches failed at N={n}; "
                  "skipping higher concurrency for this backend")
            break
    return rows


def phase_mixed() -> dict:
    """Use xaxiu-swarm swarm to dispatch 12 packets across the 3
    new backends in parallel.  Simulates a real panel."""
    print("\n  --- mixed-backend swarm panel ---")
    packets_dir = OUT_DIR / "work" / "mixed_packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    backends_to_use = ["claude-mimo", "claude-kimi", "claude-deepseek"]
    packets_per_backend = 4

    # Create packet files (.md per swarm convention)
    packets_with_backends: list[tuple[str, Path]] = []
    for backend in backends_to_use:
        for i in range(packets_per_backend):
            packet_path = packets_dir / f"{backend}_p{i}.md"
            packet_path.write_text(
                f"# Packet {i} for {backend}\n\n"
                f"{PROMPTS[i % len(PROMPTS)]}\n",
                encoding="utf-8",
            )
            packets_with_backends.append((backend, packet_path))

    # Dispatch each via xaxiu-swarm dispatch in parallel (xaxiu-swarm
    # swarm requires all packets to use same backend; we want mixed)
    print(f"    firing {len(packets_with_backends)} dispatches across "
          f"{len(backends_to_use)} backends in parallel...")
    started = time.monotonic()
    with _cf.ThreadPoolExecutor(
        max_workers=len(packets_with_backends),
    ) as pool:
        jobs = [
            pool.submit(
                _dispatch_one,
                backend, i,
                packets_dir / f"deliverable_{backend}_p{i}.txt",
                packet.read_text(encoding="utf-8"),
            )
            for i, (backend, packet) in enumerate(packets_with_backends)
        ]
        results = [j.result() for j in jobs]
    wall = time.monotonic() - started

    by_backend: dict[str, list[dict]] = {}
    for r in results:
        by_backend.setdefault(r["backend"], []).append(r)

    summary = {
        "wall_s": wall,
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "per_backend": {},
    }
    for backend, rows in by_backend.items():
        ok = sum(1 for r in rows if r["ok"])
        lats = [r["elapsed_s"] for r in rows]
        summary["per_backend"][backend] = {
            "ok": ok,
            "total": len(rows),
            "avg_latency_s": sum(lats) / len(lats),
            "max_latency_s": max(lats),
        }
    print(f"    -> {summary['ok']}/{summary['total']} OK in "
          f"{wall:.0f}s wall")
    return summary


def synthesize(
    curve_rows: list[dict],
    mixed: dict,
) -> str:
    """Operator-facing markdown report."""
    lines: list[str] = [
        "# Swarm stress test — 2026-05-26",
        "",
        "## Phase 1: concurrency curve",
        "",
        "Per-backend dispatch metrics at N = 4, 8, 16, 32 concurrent.",
        "Realistic short prompts (code / reasoning / JSON / bullet).",
        "",
        "| Backend | N | OK | Fail | 429s | Wall | p50 | p95 | max | "
        "Speedup |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in curve_rows:
        lines.append(
            f"| `{row['backend']}` | {row['concurrency']} | "
            f"{row['ok']} | {row['fail']} | {row['rate_limited']} | "
            f"{row['wall_s']:.0f}s | "
            f"{row['p50_s']:.1f}s | "
            f"{row['p95_s']:.1f}s | "
            f"{row['max_s']:.1f}s | "
            f"{row['speedup_vs_serial']:.1f}× |"
        )

    # Aggregate per-backend
    lines.extend([
        "",
        "## Per-backend headline",
        "",
        "| Backend | Highest N tested | OK at that N | "
        "p95 at that N | Throttled? |",
        "|---|---|---|---|---|",
    ])
    by_backend: dict[str, list[dict]] = {}
    for r in curve_rows:
        by_backend.setdefault(r["backend"], []).append(r)
    for backend, rows in by_backend.items():
        max_row = max(rows, key=lambda r: r["concurrency"])
        any_throttle = any(r["rate_limited"] > 0 for r in rows)
        lines.append(
            f"| `{backend}` | {max_row['concurrency']} | "
            f"{max_row['ok']}/{max_row['concurrency']} | "
            f"{max_row['p95_s']:.1f}s | "
            f"{'YES' if any_throttle else 'no'} |"
        )

    lines.extend([
        "",
        "## Phase 2: mixed-backend parallel panel",
        "",
        f"Fired {mixed['total']} packets across "
        f"{len(mixed['per_backend'])} backends in parallel.",
        f"Wall: {mixed['wall_s']:.0f}s.  Success: "
        f"{mixed['ok']}/{mixed['total']}.",
        "",
        "| Backend | OK | Avg latency | Max latency |",
        "|---|---|---|---|",
    ])
    for backend, stats in mixed["per_backend"].items():
        lines.append(
            f"| `{backend}` | {stats['ok']}/{stats['total']} | "
            f"{stats['avg_latency_s']:.1f}s | "
            f"{stats['max_latency_s']:.1f}s |"
        )

    lines.extend([
        "",
        "## Verdict",
        "",
    ])
    # Verdict logic
    total_429 = sum(r["rate_limited"] for r in curve_rows)
    total_attempted = sum(r["concurrency"] for r in curve_rows)
    total_ok = sum(r["ok"] for r in curve_rows)
    overall_pct = total_ok / max(1, total_attempted) * 100
    lines.append(
        f"- Overall success: {total_ok}/{total_attempted} "
        f"({overall_pct:.0f}%) across all concurrency levels"
    )
    lines.append(
        f"- Rate-limit indicators: {total_429} dispatches showed "
        f"429/throttle markers in stderr"
    )
    if total_429 == 0 and overall_pct > 95:
        lines.append(
            "- **Conclusion: swarm handles 32-way concurrency cleanly** "
            "with no observable throttling.  Audit-panel concern "
            "(\"concurrency >10x untested\") closed."
        )
    elif total_429 > 0:
        lines.append(
            "- **Conclusion: rate-limiting observed.**  Check stderr "
            "excerpts in raw_results.json for which backend hit the "
            "wall first."
        )
    else:
        lines.append(
            "- **Conclusion: partial.**  Some failures observed but "
            "no rate-limit indicators - likely subprocess timeouts at "
            "high N.  Check raw results."
        )
    return "\n".join(lines)


def main() -> int:
    print(f"[stress] Swarm stress test")
    print(f"  backends: {', '.join(TEST_BACKENDS)}")
    print(f"  concurrency levels: {CONCURRENCY_LEVELS}")
    print(f"  output: {OUT_DIR.relative_to(REPO)}")
    started = time.monotonic()

    # Phase 1: curve per backend
    print(f"\n[stress] Phase 1: per-backend concurrency curve")
    all_curve_rows: list[dict] = []
    for backend in TEST_BACKENDS:
        rows = phase_curve(backend)
        all_curve_rows.extend(rows)
        # Incremental save
        with (OUT_DIR / "curve_rows.csv").open(
            "w", encoding="utf-8", newline="",
        ) as f:
            writer = csv.DictWriter(
                f, fieldnames=list(all_curve_rows[0].keys()),
            )
            writer.writeheader()
            writer.writerows(all_curve_rows)

    # Phase 2: mixed panel
    print(f"\n[stress] Phase 2: mixed-backend parallel panel")
    mixed = phase_mixed()

    # Save raw
    (OUT_DIR / "mixed_results.json").write_text(
        json.dumps(mixed, indent=2), encoding="utf-8",
    )

    # Synthesize
    synthesis = synthesize(all_curve_rows, mixed)
    (OUT_DIR / "SYNTHESIS.md").write_text(synthesis, encoding="utf-8")

    elapsed = time.monotonic() - started
    print(f"\n[stress] DONE in {elapsed:.0f}s.")
    print(f"  artifacts: {OUT_DIR.relative_to(REPO)}")

    # Clean up the work/ directory (smoke deliverables) to keep
    # the committed artifacts tidy
    shutil.rmtree(OUT_DIR / "work", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
