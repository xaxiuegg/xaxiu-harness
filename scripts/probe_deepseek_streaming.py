"""W5-MM regression probe: DeepSeek streaming latency monitor.

Original purpose (pre-W5-MM): measure whether DeepSeek benefits from
streaming.  Verdict was yes — 10.6s → 2.8s total (4x), 0.8s TTFB
(13x faster).  Streaming was then implemented in DeepSeekConcrete
2026-05-23.

Post-W5-MM purpose: regression detector.  Both "modes" now stream
internally (harness path via DeepSeekConcrete.dispatch, raw path via
direct httpx).  If the harness path ever regresses to non-streaming,
the latency gap reappears and operators can debug from there.

Run: python -X utf8 scripts/probe_deepseek_streaming.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


PROMPT = (
    "Write a 3-line docstring for a Python function named `is_palindrome(s: str) -> bool` "
    "that ignores non-alphanumeric characters and is case-insensitive.  Output only the "
    "docstring (triple-quoted), nothing else."
)
MODEL = "deepseek-v4-flash"


def probe_nonstreaming() -> dict:
    """Use the existing harness DeepSeekConcrete path."""
    engine = get_engine("deepseek", prefer_dpapi=False)
    started = time.monotonic()
    resp = engine.dispatch(PROMPT, MODEL, {})
    latency_ms = int((time.monotonic() - started) * 1000)
    return {
        "mode": "harness_nonstreaming",
        "latency_ms": latency_ms,
        "success": resp.success,
        "text_len": len(resp.text or ""),
        "ttfb_ms": latency_ms,  # non-streaming TTFB == total latency
        "first_120_chars": (resp.text or "")[:120],
    }


def probe_streaming() -> dict:
    """Direct httpx call with stream=True so we can measure TTFB."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return {"mode": "streaming", "error": "DEEPSEEK_API_KEY not set"}

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 32768,
        "temperature": 0.0,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "xaxiu-harness-probe/W5-MM",
    }

    started = time.monotonic()
    ttfb_ms: int | None = None
    chunks: list[str] = []
    with httpx.Client(verify=True, timeout=httpx.Timeout(read=120, connect=10, write=10, pool=10)) as client:
        with client.stream(
            "POST", "https://api.deepseek.com/v1/chat/completions",
            headers=headers, json=payload,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                if ttfb_ms is None:
                    ttfb_ms = int((time.monotonic() - started) * 1000)
                if line.startswith("data: "):
                    data_str = line[6:]
                elif line.startswith("data:"):
                    data_str = line[5:]
                else:
                    continue
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        chunks.append(delta["content"])
    total_ms = int((time.monotonic() - started) * 1000)
    text = "".join(chunks)
    return {
        "mode": "streaming",
        "latency_ms": total_ms,
        "ttfb_ms": ttfb_ms,
        "success": bool(text),
        "text_len": len(text),
        "first_120_chars": text[:120],
    }


def main() -> int:
    print(f"[probe] prompt: {PROMPT[:80]}... ({len(PROMPT)} chars)", flush=True)
    print(f"[probe] model: {MODEL}", flush=True)
    print()

    print("--- non-streaming (current harness path) ---", flush=True)
    a = probe_nonstreaming()
    print(json.dumps(a, indent=2), flush=True)

    print()
    print("--- streaming (raw httpx with stream=True) ---", flush=True)
    b = probe_streaming()
    print(json.dumps(b, indent=2), flush=True)

    print()
    print("--- comparison ---", flush=True)
    if a.get("success") and b.get("success"):
        ttfb_savings = (a.get("ttfb_ms") or 0) - (b.get("ttfb_ms") or 0)
        total_diff = (a.get("latency_ms") or 0) - (b.get("latency_ms") or 0)
        print(f"TTFB savings (streaming wins by ms): {ttfb_savings}", flush=True)
        print(f"Total latency diff (positive = streaming faster): {total_diff} ms", flush=True)
        if ttfb_savings > 2000:
            print("VERDICT: streaming saves >2s TTFB — worth implementing", flush=True)
        else:
            print("VERDICT: streaming TTFB delta < 2s — no significant benefit", flush=True)
    else:
        print(f"At least one probe failed; verdict deferred. a={a}, b={b}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
