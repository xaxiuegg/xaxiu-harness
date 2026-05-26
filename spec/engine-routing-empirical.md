# Engine routing — empirical recommendations

**Source**: [W14-CROSS-ENGINE-AUDIT](../coord/reviews/pattern-b-smoke-matrix/RESULTS.md) — 2026-05-26.  Three rounds of 5-category × 3-engine smoke testing through Pattern B.

This document supersedes the per-engine sections of [coord/dev_loop/dispatch-rules.md](../coord/dev_loop/dispatch-rules.md) for Pattern B (`*-via-claude`) engines.  The original swarm-based rules (xaxiu-swarm with `swarm/kimi`, `swarm/kimi-api`, `swarm/deepseek`) still apply for that path.

## Headline

**All three Pattern B engines are production-ready across all 5 test categories.**  As of the W14-CROSS-ENGINE-AUDIT 2026-05-26: 15/15 dispatches succeed in 50s wall-clock for the full matrix, $0.23 total cost.

| Engine | Avg latency | Total cost | Tokens out | Cost / success | Default model |
|---|---|---|---|---|---|
| `kimi-via-claude` | 17.9s | $0.068 | 1,406 | $0.014 | `kimi-for-coding` |
| `mimo-via-claude` | 9.3s | $0.075 | 596 | $0.015 | (provider default) |
| `deepseek-via-claude` | 10.0s | $0.088 | 608 | $0.018 | `deepseek-v4-flash` |

**Latency:** `mimo-via-claude` is fastest on average; `deepseek-via-claude` close second (since W14-CROSS-ENGINE-AUDIT flipped its default to v4-flash); `kimi-via-claude` has highest variance — fast on simple prompts (~8s), slow on long-context (50s).

**Cost:** `kimi-via-claude` lowest matrix cost.  Differences are small (~$0.02 across the trio); workload variance dominates.

**Output verbosity:** `kimi-via-claude` produces 2.3× more output tokens than the others for equivalent prompts.  For "summarize in 1 sentence" tasks it routinely returns 100-200 tokens (vs MiMo's 19-47 and DeepSeek-flash's 29-43).  For long-context reasoning it produces 5-9× more output.

## Routing decisions by task class

### Default routing — use this when no special requirement applies

For routine code generation, reasoning, debugging, and short-context tasks:

```
mimo-via-claude  ← speed (9.3s avg), conciseness (lowest token-out)
```

MiMo handles all 5 test categories reliably with the fastest mean latency.  Output style is terse and direct; consumers parse it easily.

### Latency-sensitive (panel work, dashboards)

When the operator is waiting and ≤ 15s matters:

```
mimo-via-claude  (9.3s avg)        ← first choice
deepseek-via-claude (10.0s avg)    ← second choice (v4-flash default)
```

Kimi-via-claude has highest variance; avoid for latency-critical paths unless you've already paid the cost.

### Long-context / detailed explanation

When the operator wants 500+ token elaboration (root-cause writeups, architectural reviews, post-mortems):

```
kimi-via-claude   ← produces the most elaboration per dispatch
```

The 50s latency is acceptable when the output is the deliverable.

### Cost-critical / high-volume

For background tasks where dollars matter and you'll dispatch thousands:

```
kimi-via-claude   ← cheapest in the matrix ($0.068 for 5 categories)
mimo-via-claude   ← close second
```

But: at this scale (~$30/month operator budget), all three are equivalent.  Cost matters more for `swarm/*` direct-PAYG paths than for Pattern B subscription paths.

### Multimodal-adjacent (markdown image refs in prompts)

Prompts containing `![alt](path)` markdown image syntax pre-W14 stalled all three engines at the Claude Code CLI layer.  Since W14-MULTIMODAL-STRIP-MARKDOWN-REFS landed (2026-05-26), all three handle stripped refs reliably:

```
mimo-via-claude or kimi-via-claude   ← either works
deepseek-via-claude                  ← will fire a `WARNING` log because
                                        the multimodal-marker heuristic
                                        still matches *.png in the original
                                        text — informational only
```

To suppress the DeepSeek warning entirely on text-only-with-markdown-refs:

```bash
HARNESS_DEEPSEEK_MULTIMODAL_REFUSE=  # leave unset (default)
```

If you need DeepSeek to fail-fast instead of warn:

```bash
HARNESS_DEEPSEEK_MULTIMODAL_REFUSE=1
```

### Ship-critical / cross-engine audit

When a result must be re-verified against an independent engine before integration:

```
First engine:  any of the three
Audit engine:  one of the OTHER two   ← never the same engine
Premium tier:  pass `extra_args={"model": "deepseek-v4-pro"}` to
               escalate DeepSeek's deeper-reasoning mode for the audit
               step only
```

Triangulation (3-engine consensus) is rarely needed but available via the panel dispatcher.

## Engine-specific quirks

### kimi-via-claude

- **High output-token tendency**: prompts asking for "one sentence" return 100-200 tokens.  Mitigate with explicit token budget in the prompt: "in ≤ 20 words" produces tighter output than "in one sentence".
- **Long-context spikes**: prompts > 2KB occasionally hit 50s latency.  Set `extra_args["timeout_s"]` ≥ 120 for long inputs; the engine's default `_DEFAULT_TIMEOUT_S = 300` handles this but check that callers aren't passing a tighter override.
- **Endpoint**: `https://api.kimi.com/coding` (provider-allowlisted via Claude Code legitimate UA — W14-KIMI-VIA-CLAUDE 2026-05-26).
- **Model identifier**: `kimi-for-coding` — Moonshot's stable alias for the current production code model (as of 2026-05-26 maps to kimi-k2.6-code).

### mimo-via-claude

- **Most concise**: returns the lowest token count for equivalent prompts.  For applications that parse model output (e.g. extracting just the code block), this saves downstream tokens.
- **Token Plan vs PAYG**: the engine auto-detects the operator's MIMO_API_KEY prefix and routes to the correct endpoint (`tp-` → Token Plan; `mp-` or other → PAYG).  No operator action required.
- **Multimodal-safe**: handles `(image: alt)` stripped refs without warning.

### deepseek-via-claude

- **Default model**: `deepseek-v4-flash` (W14-CROSS-ENGINE-AUDIT 2026-05-26 flipped from v4-pro).  v4-flash is ~5× cheaper than v4-pro at comparable code/reasoning quality per operator's `feedback_default_deepseek_v4_flash` memory.  Use v4-pro only for ship-blocking audits via `extra_args={"model": "deepseek-v4-pro"}`.
- **Multimodal warning**: the engine logs a WARNING when prompts contain image/video/audio/document markers because DeepSeek's Anthropic-compat layer silently drops these blocks.  The strip helper (W14-MULTIMODAL-STRIP-MARKDOWN-REFS) handles markdown image refs upstream; the warning may still fire for `.png` file-extension mentions in prose, which is informational.
- **Default timeout**: 180s (W14-DEEPSEEK-TIMEOUT-BUMP — raised from the engine-base 90s default because DeepSeek's Anthropic-compat layer is consistently slower than direct OpenAI-format).
- **v4-pro caveat**: when explicitly overridden to v4-pro, DeepSeek's thinking mode can eat the output budget on surgical FIND/REPLACE patches.  Pair v4-pro requests with prompt instructions like "output text only, no thinking tools" per memory `feedback_deepseek_v4_no_tools_packet`.

## When to use which: a quick decision tree

```
Is the task speed-critical (panel/dashboard, < 15s budget)?
  ├── YES  → mimo-via-claude (fallback: deepseek-via-claude)
  └── NO
       │
       Does the task need verbose elaboration (detailed writeup)?
       ├── YES → kimi-via-claude
       └── NO
            │
            Is it a ship-critical audit step (must verify with a
            second engine)?
            ├── YES → use a DIFFERENT engine than the first.  For
            │        max-reasoning, override DeepSeek to v4-pro.
            └── NO  → mimo-via-claude (default)
```

## What we still don't know (deferred coverage)

The smoke matrix tests 5 categories.  Additional coverage gaps to be addressed in future audits:

| Gap | Why it matters | Estimated effort |
|---|---|---|
| Tool-use through `--print --bare` | The harness's primary use case is multi-agent dispatch which involves tool calls.  Bare mode may or may not expose tools to the model. | ~1h |
| Streaming via `--output-format stream-json` | Long-running dispatches would benefit from progress updates.  Untested. | ~30min |
| Real multimodal file attachment | Tested markdown-ref stripping; haven't tested `--file image.png` flag through Pattern B. | ~30min |
| High-concurrency stress (8/16/24 parallel) | Current semaphore = 4.  Higher concurrency could 2-4× throughput if endpoints support it. | ~1h |
| Linux / macOS wrapper script behavior | Smoke matrix runs Windows + Git-Bash only.  Operator targets cross-platform. | ~1h |

These are tracked in STATUS.csv as `W14-PATTERN-B-*` rows.

## Re-running the audit

```bash
python scripts/pattern_b_smoke_matrix.py
```

Total runtime: ~50s.  Total cost: ~$0.23.  Output: `coord/reviews/pattern-b-smoke-matrix/RESULTS.md` + `raw_results.json`.

**Recommended cadence**: monthly, or after any of these:

- Provider API endpoint change (Kimi/MiMo/DeepSeek announce a new path)
- Claude Code CLI version bump (subprocess host)
- Operator's monthly budget reset (good time to verify pool health)

## Programmatic recommendation

For programmatic routing, use:

```bash
harness engine recommend <task-class>
```

Where `<task-class>` is one of: `default`, `latency`, `verbose`, `cost`, `multimodal`, `audit`.  Output is the recommended engine name as a single token, exit 0 on success.

Example:

```bash
$ harness engine recommend latency
mimo-via-claude
```

Pipe into dispatch:

```bash
ENGINE=$(harness engine recommend default)
python -c "from harness.engines.concrete import get_engine; \
    e = get_engine('$ENGINE'); \
    r = e.dispatch('explain X', '', {}); \
    print(r.text)"
```
