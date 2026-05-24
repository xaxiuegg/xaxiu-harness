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
