"""Verify W4-G finding: source-laden packets break Kimi/MiMo, work on DeepSeek.

W4-G found:
  kimi/kimi-for-coding      0/5  100% silent empty on ~4KB source-laden
  mimo/mimo-v2.5-pro        2/5  60% silent empty on ~4KB source-laden
  mimo/mimo-v2.5 (Std)      3/5  40% silent empty on ~4KB source-laden
  deepseek/deepseek-v4-flash 5/5  reliable on same packets

W4-G assigned each FUT to ONE engine.  This verification sends the SAME
3 source-laden packets to ALL 3 engines so we can directly compare
on identical input.  3 packets × 3 engines = 9 dispatches.

Output: coord/coverage/verify_source_laden_<stamp>.json
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


# Three source-laden FUTs, sized small / medium / large
FUTS = [
    ("small_source",  "src/harness/heartbeat.py"),        # ~1-2 KB
    ("medium_source", "src/harness/coord/run_state.py"),  # ~2-4 KB
    ("large_source",  "src/harness/coord/coordinator.py"),  # ~10-15 KB
]

ENGINES = [
    ("kimi",     "kimi-for-coding"),
    ("mimo",     "mimo-v2.5-pro"),
    ("deepseek", "deepseek-v4-flash"),
]

INSTRUCTIONS = """\
You are a code-review agent.  Read the source below and produce:

1. A one-line summary of what this module does (< 80 chars).
2. The single most likely failure mode in it (< 80 chars).
3. Your confidence that the module is correct, 0.0–1.0.

Output **JSON only**, no preamble or markdown fence:

{
  "summary": "...",
  "likely_failure": "...",
  "confidence": 0.0
}

# Source under review
"""


@dataclass
class VerifyResult:
    fut: str
    source_path: str
    source_bytes: int
    engine: str
    model: str
    success: bool
    latency_ms: int
    tokens_in: int
    tokens_out: int
    text_len: int
    text_preview: str
    parseable_json: bool
    error: str | None = None


def _build_packet(source_path: str) -> tuple[str, int]:
    p = Path(source_path)
    if not p.exists():
        return INSTRUCTIONS + f"(file not found: {source_path})\n", 0
    src = p.read_text(encoding="utf-8")
    packet = INSTRUCTIONS + f"\n## {source_path} ({len(src)} bytes)\n\n```python\n{src}\n```\n"
    return packet, len(src)


def _parses_as_json(text: str) -> bool:
    import re
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        return False
    try:
        json.loads(m.group(0))
        return True
    except json.JSONDecodeError:
        return False


def main() -> int:
    out_dir = Path("coord/coverage")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    results: list[VerifyResult] = []
    total = len(FUTS) * len(ENGINES)
    print(f"=== source-laden verification: {total} dispatches "
          f"({len(FUTS)} packets × {len(ENGINES)} engines) ===", flush=True)

    # For each packet, dispatch to all 3 engines so we can directly compare
    for fut_name, source_path in FUTS:
        packet, src_bytes = _build_packet(source_path)
        print(f"\n--- {fut_name} ({src_bytes} bytes source from {source_path}) ---",
              flush=True)
        for engine_name, model in ENGINES:
            eng = get_engine(engine_name, prefer_dpapi=False)
            started = time.monotonic()
            try:
                # W5-W 2026-05-23: operator directive "do not limit
                # max_tokens of unlimited-subscription engines".  Pass {}
                # so engine defaults apply (Kimi 200k, MiMo 131k, DS 32k).
                resp = eng.dispatch(packet, model, {})
                latency = int((time.monotonic() - started) * 1000)
                ok = bool(resp.success and (resp.text or "").strip())
                text = resp.text or ""
                tokens_in = getattr(resp, "tokens_in", 0)
                tokens_out = getattr(resp, "tokens_out", 0)
                err = resp.error
            except Exception as exc:
                latency = int((time.monotonic() - started) * 1000)
                ok = False
                text = ""
                tokens_in = tokens_out = 0
                err = f"{type(exc).__name__}: {exc}"

            parseable = _parses_as_json(text) if ok else False
            r = VerifyResult(
                fut=fut_name, source_path=source_path, source_bytes=src_bytes,
                engine=engine_name, model=model,
                success=ok, latency_ms=latency,
                tokens_in=tokens_in, tokens_out=tokens_out,
                text_len=len(text), text_preview=text[:120],
                parseable_json=parseable, error=err,
            )
            results.append(r)

            mark = "OK " if (ok and parseable) else ("?? " if ok else "FAIL")
            tok_str = (f"  in={tokens_in:>4} out={tokens_out:>4}" if tokens_in or tokens_out
                       else "  tokens=?")
            print(f"  [{engine_name:<8}/{model:<22}] {mark} "
                  f"{latency:>6}ms  text_len={len(text):>5}{tok_str}"
                  f"  err={err}", flush=True)

    # Matrix summary: rows=packets, cols=engines, cell=OK/EMPTY/FAIL
    print("\n=== matrix (packet × engine) ===", flush=True)
    print(f"{'packet':16} | " + " | ".join(f"{e:<10}" for e, _ in ENGINES), flush=True)
    print("-" * (16 + 3 + sum(13 for _ in ENGINES)), flush=True)
    by_fut: dict[str, dict[str, str]] = {}
    for r in results:
        by_fut.setdefault(r.fut, {})
        verdict = ("OK" if (r.success and r.parseable_json)
                   else "TEXT-ONLY" if r.success else "EMPTY/FAIL")
        by_fut[r.fut][r.engine] = verdict
    for fut_name, _ in FUTS:
        cells = [by_fut[fut_name].get(e, "?") for e, _ in ENGINES]
        print(f"{fut_name:<16} | " + " | ".join(f"{c:<10}" for c in cells), flush=True)

    # Cost rollup using W4-K tokens
    print("\n=== cost rollup (tokens from W4-K) ===", flush=True)
    by_engine: dict[str, dict[str, int]] = {}
    for r in results:
        agg = by_engine.setdefault(r.engine,
                                    {"in": 0, "out": 0, "ok": 0, "fail": 0})
        agg["in"] += r.tokens_in
        agg["out"] += r.tokens_out
        agg["ok"] += 1 if (r.success and r.parseable_json) else 0
        agg["fail"] += 1 if not (r.success and r.parseable_json) else 0
    for engine_name, _ in ENGINES:
        agg = by_engine.get(engine_name, {"in": 0, "out": 0, "ok": 0, "fail": 0})
        print(f"  {engine_name:<10}  ok={agg['ok']}/3  fail={agg['fail']}/3  "
              f"in={agg['in']}  out={agg['out']}", flush=True)

    report_path = out_dir / f"verify_source_laden_{stamp}.json"
    report_path.write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_dispatches": len(results),
        "engines": [{"name": e, "model": m} for e, m in ENGINES],
        "futs": [{"name": n, "source": p} for n, p in FUTS],
        "by_fut_matrix": by_fut,
        "by_engine": by_engine,
        "results": [asdict(r) for r in results],
    }, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
