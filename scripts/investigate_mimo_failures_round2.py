"""MiMo investigation round 2: test the two untested variables.

Round 1 found 8/8 tests passed. The variables NOT tested were:
  - Very large prompts (96KB / ~25K tokens)
  - Concurrent dispatches (ThreadPoolExecutor max_workers=8)

This round tests those directly to isolate which one triggers
the "internal" error.
"""
from __future__ import annotations

import concurrent.futures as _cf
import json
import sys
import time
from pathlib import Path

import httpx

# UTF-8 stdout
for _s in ("stdout", "stderr"):
    _stream = getattr(sys, _s, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.secrets.resolve import resolve_key  # noqa: E402
from harness.engines.concrete import (  # noqa: E402
    _resolve_mimo_upstream, _make_mimo_user_agent,
)

API_KEY = resolve_key("MIMO_API_KEY")


def raw_mimo(prompt: str, max_tokens: int = 5000,
              timeout_sec: float = 180.0,
              model: str = "mimo-v2.5-pro") -> dict:
    started = time.monotonic()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.6,
    }
    try:
        with httpx.Client(verify=True, timeout=timeout_sec) as client:
            r = client.post(
                _resolve_mimo_upstream(API_KEY),
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "User-Agent": _make_mimo_user_agent(),
                },
                json=payload,
            )
            elapsed = time.monotonic() - started
            try:
                body = r.json()
            except json.JSONDecodeError:
                body = {"raw_text": r.text[:600]}
            return {
                "ok": r.status_code == 200,
                "http_status": r.status_code,
                "elapsed_s": elapsed,
                "body": body,
                "prompt_len": len(prompt),
            }
    except Exception as exc:
        return {"ok": False, "exception_type": type(exc).__name__,
                "msg": str(exc)[:400],
                "elapsed_s": time.monotonic() - started}


def _load_panel_source() -> str:
    """Load the exact 96KB source pack the panel used."""
    parts = []
    files = [
        "coord/reviews/master-audit-2026-05-25.md",
        "coord/reviews/horizon-c-internal-tool-plan.md",
        "coord/reviews/bloat-audit-2026-05-25.md",
        "docs/AGENT_QUICKSTART.md",
        "docs/INTERNAL_OPERATOR_RUNBOOK.md",
    ]
    for rel in files:
        p = REPO / rel
        if p.exists():
            parts.append(f"\n\n=== FILE: {rel} ===\n\n"
                         f"{p.read_text(encoding='utf-8', errors='replace')}")
    status_path = REPO / "coord/STATUS.csv"
    if status_path.exists():
        lines = status_path.read_text(encoding="utf-8").splitlines()
        parts.append(f"\n\n=== STATUS.csv (last 60 rows) ===\n\n"
                     f"{chr(10).join(lines[-60:])}")
    return "".join(parts)


def _summarize(test_id: str, result: dict) -> None:
    print(f"=== {test_id} ===")
    if result.get("ok"):
        body = result.get("body", {})
        choices = body.get("choices", [])
        if choices:
            usage = body.get("usage", {})
            text = choices[0].get("message", {}).get("content", "")
            print(f"  OK in {result['elapsed_s']:.1f}s")
            print(f"  tokens in/out: {usage.get('prompt_tokens', '?')}/"
                  f"{usage.get('completion_tokens', '?')}")
            print(f"  text len: {len(text)} chars")
            print(f"  preview: {text[:200]!r}")
        else:
            print(f"  OK but unexpected body: "
                  f"{json.dumps(body)[:500]}")
    else:
        print(f"  FAIL in {result.get('elapsed_s', 0):.1f}s")
        print(f"  exception: {result.get('exception_type')}")
        print(f"  http_status: {result.get('http_status')}")
        print(f"  msg: {result.get('msg', '')[:400]}")
        if "body" in result:
            print(f"  body: {json.dumps(result['body'])[:500]}")
    print()


def main() -> int:
    source = _load_panel_source()
    print(f"Source pack: {len(source)} chars ({len(source)/4:.0f} approx tokens)\n")

    # T9: the EXACT failing prompt, sequential (one request)
    panel_prompt = (
        f"Render a strategic SHIP/DROP verdict on the following plan.\n\n"
        f"{source}\n\n"
        f"List the top 3 SHIP items + top 3 DROP items.  Output Markdown."
    )
    _summarize(
        f"T9: panel-size prompt ({len(panel_prompt)} chars) SEQUENTIAL",
        raw_mimo(panel_prompt, max_tokens=5000),
    )

    # T10: same prompt, 3 concurrent dispatches (the panel's pattern)
    print("=== T10: 3 concurrent dispatches of T9 prompt ===")
    started = time.monotonic()
    with _cf.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(raw_mimo, panel_prompt, 5000) for _ in range(3)]
        for i, fut in enumerate(_cf.as_completed(futures)):
            r = fut.result()
            flag = "OK" if r.get("ok") else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s" if r.get("ok")
                     else f"{r.get('exception_type', '?')} {r.get('msg', '')[:100]}")
            print(f"  [#{i+1}] {flag}  {extra}")
            if not r.get("ok") and "body" in r:
                print(f"        body: {json.dumps(r['body'])[:300]}")
    print(f"  total wall: {time.monotonic() - started:.0f}s")
    print()

    # T11: max_tokens=8000 (panel value) with panel content, sequential
    _summarize(
        f"T11: panel-size prompt, max_tokens=8000, SEQUENTIAL",
        raw_mimo(panel_prompt, max_tokens=8000),
    )

    # T12: incremental size — find the breaking point
    for size_kb in [25, 50, 75, 100]:
        truncated = source[:size_kb * 1024]
        p = (f"Summarize this in 5 bullets:\n\n{truncated}")
        _summarize(
            f"T12-{size_kb}KB: incremental size (max_tokens=2000)",
            raw_mimo(p, max_tokens=2000),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
