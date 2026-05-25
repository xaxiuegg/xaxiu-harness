"""MiMo investigation Round 3: address Kimi's peer-review critique.

Kimi pointed out (correctly) that my Round-2 attribution of T12-50KB
and T12-75KB single-shot failures to 'server load variance' was
unsound.  Single-shot failures on a black-box remote service can't
distinguish deterministic thresholds from transient noise.

This script retries each failed configuration 3 times sequentially
+ captures response headers + logs the exact exception type.

Hypothesis: if the 50KB/75KB failures repeat across all 3 retries,
they're a real threshold (or specific-payload trigger).  If they
succeed on retry, they were genuine transient noise — and my
'server load variance' attribution was right, just under-evidenced.

Also retries T11 (97KB + 8000 tokens) which was the clearest signal
that high max_tokens combined with large prompts is unstable.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

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
            # Capture response headers per Kimi's recommendation
            interesting_headers = {
                k: v for k, v in r.headers.items()
                if k.lower() in {"x-request-id", "server", "via",
                                  "x-served-by", "cf-ray", "x-trace-id",
                                  "x-mimo-request-id"}
            }
            try:
                body = r.json()
            except json.JSONDecodeError:
                body = {"raw_text": r.text[:400]}
            return {
                "ok": r.status_code == 200,
                "http_status": r.status_code,
                "elapsed_s": elapsed,
                "headers": interesting_headers,
                "body_keys": list(body.keys()) if isinstance(body, dict) else None,
                "completion_tokens": body.get("usage", {}).get(
                    "completion_tokens", None) if isinstance(body, dict) else None,
                "prompt_tokens": body.get("usage", {}).get(
                    "prompt_tokens", None) if isinstance(body, dict) else None,
            }
    except Exception as exc:
        return {"ok": False, "exception_type": type(exc).__name__,
                "msg": str(exc)[:300],
                "elapsed_s": time.monotonic() - started}


def _load_source() -> str:
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
    return "".join(parts)


def run_retry_set(label: str, prompt: str, max_tokens: int, n: int = 3) -> list[dict]:
    """Run the same config N times sequentially with 2s gap between."""
    print(f"=== {label} (n={n}) ===")
    print(f"  prompt: {len(prompt)} chars, max_tokens={max_tokens}")
    results = []
    for i in range(n):
        r = raw_mimo(prompt, max_tokens=max_tokens)
        flag = "OK" if r.get("ok") else "FAIL"
        if r.get("ok"):
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"in/out: {r.get('prompt_tokens')}/"
                     f"{r.get('completion_tokens')}t")
        else:
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"{r.get('exception_type', '?')}: "
                     f"{r.get('msg', '')[:80]}")
        headers_short = " ".join(f"{k}={v[:30]}" for k, v
                                 in (r.get("headers") or {}).items())
        print(f"  [#{i+1}/{n}] {flag}  {extra}  {headers_short}")
        results.append(r)
        if i < n - 1:
            time.sleep(2)  # cool-down between retries
    n_ok = sum(1 for r in results if r.get("ok"))
    print(f"  => {n_ok}/{n} ok")
    print()
    return results


def main() -> int:
    source = _load_source()
    print(f"Source pack: {len(source)} chars\n")

    # Build the same prompts that previously failed
    simple_panel_prompt = (
        f"Render a strategic SHIP/DROP verdict on the following plan.\n\n"
        f"{source}\n\n"
        f"List the top 3 SHIP items + top 3 DROP items.  Output Markdown."
    )

    summarize_template = "Summarize this in 5 bullets:\n\n{content}"

    # Test 1: re-run T11 (97KB + 8000 tokens) which failed once
    run_retry_set(
        "RETRY-T11: 97KB sequential, max_tokens=8000",
        simple_panel_prompt, max_tokens=8000, n=3,
    )

    # Test 2: re-run T12-50KB
    run_retry_set(
        "RETRY-T12-50KB: 50KB summarize, max_tokens=2000",
        summarize_template.format(content=source[:50 * 1024]),
        max_tokens=2000, n=3,
    )

    # Test 3: re-run T12-75KB
    run_retry_set(
        "RETRY-T12-75KB: 75KB summarize, max_tokens=2000",
        summarize_template.format(content=source[:75 * 1024]),
        max_tokens=2000, n=3,
    )

    # Control: re-run T12-100KB (which succeeded once) to see if that
    # was also lucky
    run_retry_set(
        "CONTROL-T12-100KB: 100KB summarize (control - was OK)",
        summarize_template.format(content=source[:100 * 1024]),
        max_tokens=2000, n=3,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
