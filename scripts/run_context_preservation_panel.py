"""Context-preservation + cost-offload panel for W11.

Operator commitment 2026-05-25: pivot to maximizing the % of tokens
an agentic coding agent can offload to subscription engines while
preserving its own context window.  UX is secondary.

This panel converges on the concrete API + return contract + storage
pattern for the agent-facing Python SDK.

5 personas:
  C1 — Context budget analyst (the scarce-resource math)
  C2 — Dispatch return-contract designer (what dispatch returns)
  C3 — Storage / on-demand retrieval (RAG for dispatched outputs)
  C4 — Cost-aware routing + telemetry (how agent KNOWS offload works)
  C5 — Agent-SDK pattern review (LangGraph / OpenAI Assistants / Anthropic native)
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO_ROOT / "coord" / "reviews" / "context-preservation-panel"


PERSONAS: list[tuple[str, str, str, str]] = [
    ("deepseek", "deepseek-v4-flash", "C1-context-budget-analyst",
     "CONTEXT BUDGET ANALYST.  Reason quantitatively: an operator "
     "agent (Claude Sonnet, ChatGPT) has ~200K context window.  Per "
     "turn the agent reads file contents (~5-50K per file), tool "
     "definitions, system prompts, prior turn history.  If the agent "
     "fires 20 harness dispatches in a session and each returns 50K "
     "of output, that's 1M tokens of dispatched content — which "
     "cannot fit even if the agent threw away everything else.  "
     "Give concrete numbers: budget per turn, leakage sources, what "
     "return shape minimizes leakage.  What's the dispatch_sync() "
     "return contract that keeps a 30-dispatch session under 100K "
     "of context growth?"),
    ("deepseek", "deepseek-v4-flash", "C2-dispatch-return-contract",
     "DISPATCH-RETURN-CONTRACT DESIGNER.  Design the Python API "
     "signature for the agent's primary call: from harness import "
     "dispatch.  What modes should dispatch() support?  Suggested "
     "candidates: (a) return path-only (agent reads on demand), "
     "(b) return summary-only (LLM-summarized one-liner), (c) "
     "return diff-only (just changed lines vs prior), (d) return "
     "full (legacy).  What's the DEFAULT, and why?  Provide the "
     "actual function signature + docstring you'd ship in W11."),
    ("mimo", "mimo-v2.5-pro", "C3-storage-retrieval",
     "STORAGE / ON-DEMAND RETRIEVAL designer.  Where do dispatched "
     "outputs live so the agent can query them later without bloating "
     "context?  Options: (a) flat files in .harness/dispatched/, "
     "(b) SQLite indexed by task_id + content_hash, (c) JSONL "
     "stream consumable by retrieve(task_id).  Design the retrieve "
     "API: harness.retrieve(task_id, scope='full'|'summary'|"
     "'diff'|'first_N_chars') so the agent can pull just what it "
     "needs.  Include caching: same packet dispatched twice should "
     "hit cache."),
    ("deepseek", "deepseek-v4-flash", "C4-cost-aware-routing",
     "COST-AWARE ROUTING + TELEMETRY.  The agent needs to KNOW its "
     "offload is working.  Today harness budget summary shows aggregate. "
     "Design the agent-facing telemetry: (a) per-session offload ratio "
     "(operator-tokens vs harness-tokens), (b) per-dispatch cost in "
     "real time so the agent can choose cheaper engines, (c) budget "
     "ceiling so a runaway dispatch loop self-halts.  Concrete: "
     "what does `from harness import budget_status()` return?  "
     "What's the cheapest-first routing decision tree?"),
    ("mimo", "mimo-v2.5-pro", "C5-agent-sdk-patterns",
     "AGENT-SDK PATTERN REVIEW.  How do LangGraph / OpenAI "
     "Assistants API / Anthropic native tools / Aider handle "
     "context preservation when an agent does heavy I/O work?  "
     "What's best-of-breed?  Specifically: tool-result format "
     "(structured vs free text), pagination / truncation defaults, "
     "context-window-aware response shaping.  What should harness "
     "adopt (vs invent)?  Where does harness differ in a way that "
     "would CONFUSE an agent already familiar with those SDKs?"),
]


def _gather_snapshot() -> str:
    """Snapshot for the panel — focused on the context-preservation question."""
    return """\
## State (post-W10, commit 0c99386)

The harness routes agentic-coding-agent dispatches to multiple
engines.  Operator's commitment 2026-05-25:

  > Maximize the % of tokens the agent can offload to subscription
  > engines while preserving the agent's own context window.
  > UX is secondary.

## Token cost reality (this session, ~14h of W9+W10+panels)

- Operator agent (Claude Code): ~1-1.5M tokens at Anthropic Sonnet
  rates (~$5-15)
- Harness dispatches: ~4.5-5M tokens, routed through subscription
  Kimi + MiMo (free marginal) + cheap DeepSeek-v4-flash (~$0.14
  total ledger spend)
- Effective offload: harness moved 75-85% of token VOLUME at 1-3%
  of dollar cost

## The agent context-window problem

An operator agent (Claude Code) has ~200K context.  Every harness
dispatch result currently returns:
- Full text response (often 5-50K tokens)
- Latency / error metadata (~500 chars)
- Engine routing trace (~1K)

If the agent fires 20 dispatches in a session and each returns 25K
of output, that's 500K of dispatched content the agent must either
(a) ingest into context immediately, breaking the budget, or (b)
truncate / summarize, defeating the purpose.

Today's `from harness import dispatch_packet` returns:

    DispatchResult(
        success=True,
        engine_used="swarm/kimi",
        fallback_chain=["kimi"],
        text=<full response>,        # <-- HUGE
        error=None,
        dispatch_id="abc-123",
        tokens_used=42000,
        cost_usd=0.0,
        tokens_in=20000,
        tokens_out=22000,
    )

The .text field is the leakage source.  An agent ingesting this
directly burns its own context proportional to dispatched output.

## What needs designing for W11

The Python API + return contract + retrieval pattern that lets an
agent fire 30 dispatches in a session AND keep its own context
under 100K growth from those dispatches.

## Operator profile

The operator builds via Claude Code (agent-driven).  Each session
is currently in the 1-2M operator-token range; harness offload is
keeping that affordable.  Optimizing this further is the highest-
leverage W11 work.
"""


_INSTRUCTIONS = """\
You are one of 5 context-preservation panel reviewers.  Use the
state snapshot + your assigned lens to answer:

## Output structure (mandatory; ≤600 words)

1. **Headline recommendation** — one sentence: the W11 design
   decision your lens converges on.

2. **Concrete numbers / API signature / data shape** — depending on
   your lens, give the actual artifact: e.g. function signature with
   defaults, JSON schema, return shape, telemetry payload.  Be
   specific.

3. **The default that maximizes context preservation** — among
   possible designs, which is the right default for an agent that
   just imports the SDK without reading docs?

4. **The escape hatch** — when the agent NEEDS the full response,
   how does it ask for it without paying the context tax for the
   common case?

5. **One risk / failure mode** specific to your lens.

No preamble.  Your lens:
"""


def _run_one(engine_name: str, model: str, pid: str, lens: str,
             snapshot: str) -> tuple[str, str, str]:
    started = time.monotonic()
    try:
        eng = get_engine(engine_name, prefer_dpapi=False)
    except RuntimeError as exc:
        return (pid, f"engine init failed: {exc}", "FAIL")
    prompt = snapshot + "\n\n---\n\n" + _INSTRUCTIONS + lens
    resp = eng.dispatch(prompt, model, {"max_tokens": 4500})
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not resp.success or not (resp.text or "").strip():
        return (pid, f"engine failed: {resp.error}", "FAIL")
    return (pid, resp.text.strip(), f"OK ({elapsed_ms}ms)")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[context-panel] gathering snapshot...", file=sys.stderr)
    snapshot = _gather_snapshot()
    (OUT_DIR / "_state_snapshot.md").write_text(snapshot, encoding="utf-8")
    print(f"[context-panel] snapshot: {len(snapshot)} chars", file=sys.stderr)

    print(f"[context-panel] dispatching {len(PERSONAS)} reviewers...",
          file=sys.stderr)
    started = time.monotonic()
    results: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_run_one, eng, model, pid, lens, snapshot): pid
            for eng, model, pid, lens in PERSONAS
        }
        for f in as_completed(futures):
            pid, text, status = f.result()
            results[pid] = (text, status)
            text_len = len(text)
            print(f"  [{status}] {pid:<34} text_len={text_len}",
                  file=sys.stderr)
    elapsed_s = time.monotonic() - started
    print(f"\n[context-panel] elapsed {elapsed_s:.0f}s", file=sys.stderr)

    for pid, (text, status) in results.items():
        (OUT_DIR / f"{pid}.md").write_text(
            f"<!-- persona={pid} status={status} -->\n\n# {pid}\n\n{text}\n",
            encoding="utf-8",
        )

    synth_lines = [
        "# Context-preservation + cost-offload panel — synthesis",
        "",
        f"_Dispatched: {len(PERSONAS)} reviewers, elapsed {elapsed_s:.0f}s_",
        "",
    ]
    for eng, model, pid, lens in PERSONAS:
        text, status = results.get(pid, ("(no response)", "MISSING"))
        synth_lines.append(f"## {pid}  ({eng}/{model})\n\n{text}\n\n---\n")
    (OUT_DIR / "SYNTHESIS.md").write_text(
        "\n".join(synth_lines), encoding="utf-8",
    )
    print(f"[context-panel] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
