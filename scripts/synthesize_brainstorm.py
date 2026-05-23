"""Synthesize the 20-agent brainstorm responses.

Reads coord/coverage/brainstorm_20agents_synthesis_input.md (the
concatenated agent responses) and dispatches to DeepSeek-v4-flash for
a single consolidated synthesis.  DeepSeek post-W5-MM streams (4x
faster), so this should complete in ~30s.

Output: coord/coverage/brainstorm_20agents_synthesis_<stamp>.md
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


INPUT = Path("coord/coverage/brainstorm_20agents_synthesis_input.md")
OUT_DIR = Path("coord/coverage")

SYNTHESIS_PROMPT = """\
Below are 20 independent agent responses (10 from Kimi K2.6, 10 from
MiMo Pro v2.5) brainstorming the autonomous-orchestrator architecture
for xaxiu-harness.  All 20 were given the SAME situation packet (the
operator's finalized "no Anthropic API key, Kimi/MiMo/DeepSeek only,
Claude only via OAuth+Task Scheduler" constraints).

Your job: produce ONE consolidated synthesis covering:

1. CONSENSUS — what do the agents agree on?  Cite specific recommendations.
2. SPLIT VOTES — where do agents disagree?  Quote the strongest version
   of each side.
3. NOVEL IDEAS — what proposals appeared that go beyond the 7 already-
   considered options listed in the situation?  Surface specific
   architectural angles the operator may not have considered.
4. KIMI-vs-MIMO PATTERNS — did the two engines bias toward different
   architectures?  Note any systematic differences.
5. CONCRETE NEXT STEPS — pick the top 3 ACTIONABLE recommendations
   that should move into spec/auto/ as queued work, in priority order
   (P0 / P1 / P2).

Aim for ~600-1000 words.  Be specific.  Cite the agent index when
quoting (e.g. "kimi-3 proposed X").  Don't summarize generically —
extract concrete proposals.

# Agent responses

{responses}
"""


def main() -> int:
    if not INPUT.exists():
        print(f"input missing: {INPUT}", file=sys.stderr)
        return 1
    responses = INPUT.read_text(encoding="utf-8")
    prompt = SYNTHESIS_PROMPT.format(responses=responses)
    print(f"[synth] dispatching {len(prompt)} chars to deepseek-v4-flash...",
          flush=True)

    eng = get_engine("deepseek", prefer_dpapi=False)
    started = time.monotonic()
    resp = eng.dispatch(prompt, "deepseek-v4-flash", {})
    latency = int((time.monotonic() - started) * 1000)

    if not resp.success:
        print(f"[synth] FAIL {latency}ms error={resp.error}", file=sys.stderr)
        return 1
    text = resp.text or ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"brainstorm_20agents_synthesis_{stamp}.md"
    out_path.write_text(
        f"<!-- engine=deepseek model=deepseek-v4-flash success=True "
        f"latency_ms={latency} tokens_in={resp.tokens_in} "
        f"tokens_out={resp.tokens_out} -->\n\n{text}",
        encoding="utf-8",
    )
    print(f"[synth] OK {latency}ms tokens_in={resp.tokens_in} "
          f"tokens_out={resp.tokens_out} chars={len(text)}", flush=True)
    print(f"  → {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
