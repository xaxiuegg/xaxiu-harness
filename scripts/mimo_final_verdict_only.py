"""Get MiMo's actual final verdict with safer parameters.

Investigation found MiMo fails on large-prompt + high-max_tokens.
This script uses sequential dispatch + max_tokens=4000 (proven safe
in T9: 5000 worked).
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

# Same source pack as the failed final-verdict run
SOURCE_FILES = [
    "coord/reviews/strategic-planning-panel15/SYNTHESIS.md",
    "coord/reviews/bloat-audit-2026-05-25.md",
    "coord/reviews/horizon-c-internal-tool-plan.md",
]

PROMPT_TEMPLATE = """You are an expert reviewer rendering a final
judgment on a strategic plan.

You are the THIRD engine (MiMo) in a 3-engine panel.  Kimi has weighed
in (truncated at section 3 but unanimous AGREE on visible items).
DeepSeek has weighed in (comprehensive AGREE with 6 minor amendments).
Now we want YOUR independent perspective on the same questions.

The OPERATOR'S DIRECTIVE: 'each agent should each try each perspective,
don't let single engine specialize in one area.'

## Source pack

{source}

## Your task — answer ALL of these sections

### Section 1: SHIP list verdict
For each, render AGREE / DISAGREE / AMEND with one-sentence reason:

1. W13-INSTALL-VERIFY (universal #1 pick)
2. W13-AUDIT-JSONL (foundational)
3. Tier 1 Shift F (auto max_tokens with safe floor)
4. harness.review() as NEW SDK function (NOT merge with dispatch)
5. harness.capabilities() SDK function + surface in `today`

### Section 2: DROP list verdict
For each, AGREE / DISAGREE / KEEP-PARTIAL:

1. W15 Plugin Architecture (entire wave)
2. W14-BEST-OF-N
3. W16 Multi-User (entire wave)
4. W17 VPS hardening (entire wave)
5. W13-PLUGIN-SANDBOX-PLAN
6. W13-BACKUP-ENCRYPTION (full AES)
7. W14-MISTRAL + W14-LOCAL-LLAMA

### Section 3: 3 key dissent rulings
Pick ONE side, no fence-sitting:

1. Merge dispatch+review or keep separate?
2. Backup: full AES encryption, secrets-redact only, or skip?
3. `harness whoami` as new CLI verb, SDK function, or both?

### Section 4: Single most important action this week
One sentence + one-sentence justification.

### Section 5: Where the prior synthesis might be wrong
What specifically would you bet differently on?

Be brutally honest.  Output Markdown.  Keep total length under 3500
tokens.
"""


def _load_source() -> str:
    parts = []
    for rel in SOURCE_FILES:
        p = REPO / rel
        if p.exists():
            parts.append(f"\n\n=== {rel} ===\n\n"
                         f"{p.read_text(encoding='utf-8', errors='replace')}")
    return "".join(parts)


def main() -> int:
    source = _load_source()
    print(f"Source pack: {len(source)} chars")

    prompt = PROMPT_TEMPLATE.format(source=source)
    print(f"Full prompt: {len(prompt)} chars\n")

    started = time.monotonic()
    payload = {
        "model": "mimo-v2.5-pro",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,           # the safe value
        "temperature": 0.6,
    }
    try:
        with httpx.Client(verify=True, timeout=180.0) as client:
            r = client.post(
                _resolve_mimo_upstream(API_KEY),
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "User-Agent": _make_mimo_user_agent(),
                },
                json=payload,
            )
            elapsed = time.monotonic() - started
            r.raise_for_status()
            body = r.json()
            text = body.get("choices", [{}])[0].get("message", {}).get(
                "content", "")
            usage = body.get("usage", {})
            print(f"OK in {elapsed:.1f}s")
            print(f"tokens in/out: {usage.get('prompt_tokens', '?')}/"
                  f"{usage.get('completion_tokens', '?')}")
            print(f"text len: {len(text)} chars\n")
            out = REPO / "coord/reviews/strategic-planning-panel15-final-verdict/mimo_final-verdict.md"
            out.write_text(text, encoding="utf-8")
            print(f"saved: {out}")
            return 0
    except Exception as exc:
        elapsed = time.monotonic() - started
        print(f"FAIL in {elapsed:.1f}s")
        print(f"  type: {type(exc).__name__}")
        print(f"  msg: {str(exc)[:400]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
