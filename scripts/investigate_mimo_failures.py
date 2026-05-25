"""Investigate why MiMo keeps returning 'internal' on strategic prompts.

The harness's MimoEngine.dispatch wraps the http call in `except Exception:`
that swallows the real error as 'internal'.  This script bypasses that
wrapper to see what MiMo's API actually returns.

Test matrix:
  T1: bare smoke — "reply pong"
  T2: medium strategic prompt, NO security/risk vocabulary
  T3: medium strategic prompt WITH security/risk vocabulary
  T4: bloat-audit content only (no synthesis)
  T5: synthesis content only (the failing prompt)
  T6: tiny synthesis prompt
  T7: try mimo-v2.5 instead of mimo-v2.5-pro
  T8: small max_tokens (1024) with synthesis content
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

# Force UTF-8 stdout so MiMo emojis don't crash the script on Windows.
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
    _resolve_mimo_upstream,
    _make_mimo_user_agent,
)

API_KEY = resolve_key("MIMO_API_KEY")


def raw_mimo_dispatch(prompt: str, model: str = "mimo-v2.5-pro",
                       max_tokens: int = 2000,
                       temperature: float = 0.6,
                       timeout_sec: float = 120.0) -> dict:
    """Bypass the harness MimoEngine wrapper; return raw API response
    or exception details."""
    if not API_KEY:
        return {"ok": False, "error": "MIMO_API_KEY not set"}
    started = time.monotonic()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
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
                body = {"raw_text": r.text[:1000]}
            return {
                "ok": r.status_code == 200,
                "http_status": r.status_code,
                "elapsed_s": elapsed,
                "response_body": body,
                "prompt_len_chars": len(prompt),
            }
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "exception_type": "HTTPStatusError",
                "status": exc.response.status_code if exc.response else None,
                "text": exc.response.text[:500] if exc.response else "",
                "elapsed_s": time.monotonic() - started}
    except httpx.TimeoutException:
        return {"ok": False, "exception_type": "TimeoutException",
                "elapsed_s": time.monotonic() - started}
    except httpx.ConnectError as exc:
        return {"ok": False, "exception_type": "ConnectError",
                "msg": str(exc),
                "elapsed_s": time.monotonic() - started}
    except Exception as exc:
        return {"ok": False, "exception_type": type(exc).__name__,
                "msg": str(exc),
                "elapsed_s": time.monotonic() - started}


def _summarize(test_id: str, prompt: str, result: dict) -> None:
    print(f"=== {test_id} ===")
    print(f"  prompt_len: {len(prompt)} chars")
    if result.get("ok"):
        body = result.get("response_body", {})
        choices = body.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")
            usage = body.get("usage", {})
            print(f"  OK in {result['elapsed_s']:.1f}s")
            print(f"  tokens in/out: {usage.get('prompt_tokens', '?')}/"
                  f"{usage.get('completion_tokens', '?')}")
            print(f"  text len: {len(text)} chars")
            print(f"  first 200 chars: {text[:200]!r}")
        else:
            print(f"  OK but no choices: {body}")
    else:
        print(f"  FAIL in {result.get('elapsed_s', 0):.1f}s")
        print(f"  exception_type: {result.get('exception_type')}")
        print(f"  http_status: {result.get('http_status')}")
        if "response_body" in result:
            body = result["response_body"]
            # Truncate
            body_s = json.dumps(body)[:600]
            print(f"  body: {body_s}")
        if "msg" in result:
            print(f"  msg: {result['msg'][:400]}")
        if "text" in result:
            print(f"  text: {result['text'][:400]}")
    print()


def main() -> int:
    print("MiMo investigation — bypassing harness wrapper\n")

    # T1: bare smoke
    _summarize(
        "T1: bare smoke (10 char prompt, max_tokens=100)",
        "reply pong",
        raw_mimo_dispatch("reply pong", max_tokens=100),
    )

    # T2: medium prompt, no risk vocabulary
    p2 = (
        "You are a project planner. Given a small Python tool with 30+ CLI "
        "commands and one user, rank these three improvements by user value: "
        "(a) auto-pick a config flag from file extension, "
        "(b) add a status summary command, "
        "(c) faster CLI startup. "
        "Output a short Markdown table with one-sentence reasons."
    )
    _summarize(
        "T2: 400-char prompt, no risk/security vocab, max_tokens=2000",
        p2,
        raw_mimo_dispatch(p2, max_tokens=2000),
    )

    # T3: same idea + security/risk vocabulary
    p3 = (
        "You are a project planner doing a SECURITY RISK review of a tool "
        "that handles API keys. Rank these THREE security MITIGATIONS by "
        "RISK-ADJUSTED return: "
        "(a) encrypt the backup archive, "
        "(b) redact secrets from cached prompts, "
        "(c) auto-rotate API keys on schedule. "
        "Identify the WORST-CASE SILENT FAILURE for each mitigation. "
        "Output Markdown."
    )
    _summarize(
        "T3: same length WITH security/risk vocabulary, max_tokens=2000",
        p3,
        raw_mimo_dispatch(p3, max_tokens=2000),
    )

    # T4: real bloat audit doc, no prompt instructions
    bloat = (REPO / "coord/reviews/bloat-audit-2026-05-25.md").read_text(
        encoding="utf-8", errors="replace",
    )
    p4 = f"Summarize the following document in 3 bullets:\n\n{bloat}"
    _summarize(
        "T4: bloat audit content (12KB) + summarize ask, max_tokens=1500",
        p4,
        raw_mimo_dispatch(p4, max_tokens=1500),
    )

    # T5: the actual failing synthesis prompt (smaller version)
    synth_excerpt = """\
The prior panel converged on 5 SHIP items. For each, render your verdict
(AGREE / DISAGREE / AMEND) with a one-sentence reason.

1. W13-INSTALL-VERIFY — universal #1 pick
2. W13-AUDIT-JSONL — universal #2 + foundational
3. Tier 1 Shift F (auto max_tokens with safe floor)
4. harness.review() as new SDK function (NOT merge)
5. harness.capabilities() SDK function + surface in today

Then list 3 things you would DROP from the plan.
Output Markdown.
"""
    _summarize(
        "T5: bare strategic question (no source), max_tokens=2000",
        synth_excerpt,
        raw_mimo_dispatch(synth_excerpt, max_tokens=2000),
    )

    # T6: try with mimo-v2.5 (not -pro)
    _summarize(
        "T6: same T5 prompt, model=mimo-v2.5 (not -pro)",
        synth_excerpt,
        raw_mimo_dispatch(synth_excerpt, model="mimo-v2.5",
                          max_tokens=2000),
    )

    # T7: very high max_tokens (might be hitting a cap)
    _summarize(
        "T7: T5 prompt with max_tokens=8000",
        synth_excerpt,
        raw_mimo_dispatch(synth_excerpt, max_tokens=8000),
    )

    # T8: very low max_tokens (under 1000)
    _summarize(
        "T8: T5 prompt with max_tokens=500",
        synth_excerpt,
        raw_mimo_dispatch(synth_excerpt, max_tokens=500),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
