# 20-agent orchestrator brainstorm — synthesis (2026-05-23)

**Operator directive**: spin up 10 Kimi + 10 MiMo agents, describe
the situation, ask each what architecture they'd recommend.

**Result**: Kimi 0/10 returned (consistent with W5-F finding — 60s
thinking-cap on ~3KB packets).  MiMo 9/10 returned with high-quality
recommendations.

## Strong convergence

**All 9 MiMo agents recommended variants of Arch C + burst-composition
queue + Windows Task Scheduler** — exactly the combination we'd
already built as **Path α (W5-T) + Path β (W5-U)**.  This validates
the architecture choice; no fundamental redesign needed.

## Novel ideas worth incorporating

### 1. Output-validation guardrail (mimo/9) — **HIGHEST VALUE**

> "Wrap engine dispatch in a validation layer: check that output
> contains only file edits (grep for FILE/REPLACE markers), no
> markdown fences, no prose explanations.  If drift is detected,
> discard and retry."

**Why it matters**: DeepSeek's ~50% prose+markdown drift currently
trips W4-A silent_no_op, requiring a SECOND engine dispatch (the
W5-O fallback) to rescue.  A pre-commit output validator could
catch drift BEFORE the worker tries to apply edits, allowing a
same-engine retry with corrective feedback — cheaper + faster than
engine fallback.

**Implementation sketch**: new `harness.engines.output_validator`
module called from `worker._parse_file_edits`.  If validation
fails, return a structured "drift detected: <signal>" error;
worker retries primary engine with explicit feedback prompt before
escalating to fallback.

### 2. SPECLIB template extraction (mimo/4)

> "Store prior Claude-authored specs as templates in
> coord/SPECLIB/.  MiMo extracts templates when composing new specs."

**Why it matters**: improves MiMo's spec quality over time without
operator intervention.  Each successful spec becomes a future
template.  Self-improving knowledge accumulation.

**Implementation sketch**: `harness queue archive --to speclib` after
successful runs.  MiMo's compose prompt includes 2-3 closest-match
templates from SPECLIB as few-shot examples.

### 3. Priority metadata on queue items (mimo/7)

> "Queue items have priority metadata.  Operator manually injects
> high-quality specs that get prioritized over MiMo-generated ones."

**Why it matters**: operator can flag specific specs as urgent
without operator presence during execution.  Simple file-naming
convention: `priority-09-foo.md` sorts before `priority-50-bar.md`.

**Implementation sketch**: `harness queue execute` already FIFO-sorts
by filename; add priority prefix convention in docs.

### 4. State-machine queue items (mimo/1)

> "Queue items aren't just specs but include intended state
> transitions / next-move metadata."

**Why it matters**: ambitious — queue items could be {spec, on_success:
next_spec_id, on_failure: rollback_action}.  Lets you encode chains.

**Verdict**: too complex for current scope.  Defer.

### 5. Windows Toast Notification on drift (mimo/9)

> "Alert operator via Windows toast notification when something
> interesting happens (drift detected, queue empty, fallback fired)."

**Why it matters**: operator awareness without polling.
**Implementation**: PowerShell `New-BurntToastNotification` or
`Show-Toast` from a notify script wired into existing observer.

### 6. Heuristic "weak spec" detection → DeepSeek upgrade (mimo/10)

> "If MiMo's composed spec is 'weak' (basic heuristic check), retry
> composition with DeepSeek.  Spends $0.001 only when MiMo is
> uncertain."

**Why it matters**: opt-in DeepSeek upgrade for unclear cases.  Lets
MiMo handle 80-90% at $0 while DeepSeek catches the hard 10-20%.

**Implementation sketch**: simple "weakness" signals — spec is too
short (<10 lines), or contains "I'm not sure", or has fewer than 3
acceptance criteria.  Auto-retry with DeepSeek.

## Engine viability for orchestrator role

| Engine | Brainstorm participation | Verdict |
|--------|-------------------------|---------|
| MiMo Pro | 9/10 succeeded with high-quality recommendations | **Production-grade orchestrator** |
| Kimi HTTP | 0/10 (60s thinking-cap on 3KB packet) | NOT viable for orchestrator-shape tasks via HTTP |
| Kimi-CLI | not tested in this brainstorm | likely viable (agentic, tool-use); test separately |
| DeepSeek | not tested as composer here (Arch B did this earlier) | strong reasoning, mild cost |

Confirmed: **MiMo Pro is the production-ready autonomous orchestrator**.

## Recommended next actions (priority order)

1. **Adopt novel idea #1** (output-validation guardrail) as W5-V.
   Highest ROI: catches DeepSeek drift before silent_no_op fires.
   ~45 min.

2. **Adopt novel idea #6** (weak-spec heuristic → DeepSeek upgrade)
   as part of Arch C composer chain.  ~20 min.

3. **Adopt novel idea #3** (priority prefix convention) — document
   only, no code change needed.

4. **Defer novel ideas #2, #4, #5** to future sessions:
   - SPECLIB: needs > 10 specs landed before it pays off
   - State-machine queue: too complex now
   - Toast notifications: nice-to-have

## Process learnings

- **Multi-engine brainstorm is a valid R&D pattern**.  20 agents at
  $0 (subscription) surfaced 6 distinct novel ideas in 8 minutes.
  Worth doing this more often for architectural decisions.
- **Kimi HTTP API stays unusable for >3KB inputs**.  Stop testing it
  in that mode; only use Kimi-CLI for big-input work.
- **MiMo's reasoning is genuinely good for architectural questions** —
  not just FILE/REPLACE.  Production trust earned.

## Operator decision points

- Implement W5-V (output validator) now or defer?
- Build the weak-spec → DeepSeek upgrade now or later?
- Want me to spin up another 20-agent brainstorm targeting Kimi-CLI
  specifically (with smaller situation packet to dodge the cap)?
