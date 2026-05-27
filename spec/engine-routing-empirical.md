# Engine routing — empirical recommendations

**Source**: [W14-CROSS-ENGINE-AUDIT](../coord/reviews/pattern-b-smoke-matrix/RESULTS.md) — 2026-05-26.  Multiple rounds of 5-category × 3-engine smoke testing through Pattern B.

**Updated 2026-05-26 evening** after two material changes:
1. **W14-MIMO-BLOAT-INVESTIGATION**: added `--tools ""` to subprocess command line.  MiMo's input tokens collapsed 22× on audit-class prompts (17,600 → 806); cost dropped 95%; latency dropped 94%.  Same fix applied uniformly to all 3 engines.
2. **MiMo-V2.5-Pro PERMANENT PRICE CUT** (effective 2026-05-26 6:00 PM PDT): input cache-miss $1.00 → $0.435 (-57%); output $3.00 → $0.87 (-71%); cache-hit $0.20 → $0.0036 (-98%).  Token Plan Pro: $50 → 38B credits (≈127M input / 63M output tokens / month).  This makes MiMo the cost leader across all task classes.

This document supersedes the per-engine sections of [coord/dev_loop/dispatch-rules.md](../coord/dev_loop/dispatch-rules.md) for Pattern B (`*-via-claude`) engines.  The original swarm-based rules (xaxiu-swarm with `swarm/kimi`, `swarm/kimi-api`, `swarm/deepseek`) still apply for that path.

## Headline

**All three Pattern B engines are production-ready across all 5 test categories.**  Post-`--tools` fix smoke matrix 2026-05-26 evening: 15/15 dispatches in 76s wall-clock, $0.16 total cost.

**Smoke-matrix numbers** (5 trivial-ish prompts × 3 engines, 76s wall, $0.16 total):

| Engine | Avg latency | Total cost | Tokens out | Cost / success | Default model |
|---|---|---|---|---|---|
| `kimi-via-claude` | 29.8s | $0.076 | 2,136 | $0.015 | `kimi-for-coding` |
| `mimo-via-claude` | 10.9s | $0.033 | 299 | $0.0067 | (provider default) |
| `deepseek-via-claude` | 5.0s | $0.055 | 591 | $0.011 | `deepseek-v4-flash` |

**Production-class corpus** (W14-MIMO-PRODUCTION-VALIDATION 2026-05-26 — 10 realistic prompts × 3 engines, 175s wall, $0.44 total):

| Engine | OK | Score | Avg latency | Total cost | Avg tokens out |
|---|---|---|---|---|---|
| `mimo-via-claude` | 10/10 | **31/31 (100%)** | **36.8s** | $0.0875 | 110 |
| `deepseek-via-claude` | 10/10 | 30/31 (97%) | **10.2s** | $0.1105 | 147 |
| `kimi-via-claude` | 10/10 | 30/31 (97%) | 39.0s | $0.2452 | 839 |

**Calibration update**: smoke-matrix latency rankings DON'T extrapolate to realistic workloads.  On the production corpus, MiMo is consistently the SLOWEST engine despite winning the smoke matrix.  But MiMo also scored highest on quality (100% programmatic pass rate) and lowest on cost — so it remains the cost-class primary, just not the latency-class primary.

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
deepseek-via-claude (10.2s avg on 10-prompt production corpus)  ← first choice
mimo-via-claude (36.8s avg, slower on every category)           ← second choice
```

**W14-MIMO-PRODUCTION-VALIDATION 2026-05-26 calibration**: the smoke matrix's "MiMo is fastest at 9.3s" finding was **trivial-prompt-only data** that did NOT extrapolate to realistic workloads.  On a 10-category production corpus (code-gen, reasoning, long-context bug-find, multi-step instructions, structured JSON, audit-class prompts, etc.), MiMo averaged 36.8s and was the SLOWEST engine on every category.  DeepSeek-flash averaged 10.2s and won every category.  Kimi averaged 39.0s.

Use DeepSeek-flash when latency matters.  Use MiMo when cost matters and you have latency budget.

### Long-context / detailed explanation

When the operator wants 500+ token elaboration (root-cause writeups, architectural reviews, post-mortems):

```
kimi-via-claude   ← produces the most elaboration per dispatch
```

The 50s latency is acceptable when the output is the deliverable.

### Cost-critical / high-volume

For background tasks where dollars matter and you'll dispatch thousands:

```
mimo-via-claude   ← cheapest in the matrix ($0.033 for 5 categories);
                   on Token Plan Pro, ~$0.008 / audit-class dispatch
                   gives you ~6,200 such dispatches / month for $50
kimi-via-claude   ← second; ~$0.076 for 5 categories
deepseek-via-claude ← $0.055 for 5; cheaper than Kimi but no
                     subscription tier
```

At the new MiMo Token Plan Pro pricing ($50 → 38B credits), high-volume work shifts decisively to MiMo.  Per-dispatch cost on a 17k-input audit-class prompt is ~$0.008.

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
- **Cheapest engine post-2026-05-26**: V2.5-Pro permanent price cut (effective 6PM PDT) makes MiMo the cost leader by ~2× over Kimi/DeepSeek.  Token Plan Pro $50/month buys ≈ 127M input / 63M output tokens, or ≈ 6,200 audit-class dispatches.
- **Token Plan vs PAYG**: the engine auto-detects the operator's MIMO_API_KEY prefix and routes to the correct endpoint (`tp-` → Token Plan; `mp-` or other → PAYG).  No operator action required.
- **Multimodal-safe**: handles `(image: alt)` stripped refs without warning.
- **Tool-call output quirk**: MiMo's model is more agent-loop-trained than Kimi or DeepSeek.  With `--tools ""` (the harness default) it produces correct text output for simple prompts but may emit unexecuted `<tool_call>...</tool_call>` XML-style markup on long structured prompts.  This is a model-trained tendency, not a harness bug — Claude Code blocks execution but doesn't strip the markup.  Workarounds: (a) post-process the response to strip `<tool_call>` blocks, or (b) add an explicit "respond in plain text, do not emit any tool-call markup" instruction in the prompt.  Without `--tools ""`, MiMo runs an actual agent loop that bloats input 22× — far worse than the markup.

### deepseek-via-claude

- **Default model**: `deepseek-v4-flash` (W14-CROSS-ENGINE-AUDIT 2026-05-26 flipped from v4-pro).  v4-flash is ~5× cheaper than v4-pro at comparable code/reasoning quality per operator's `feedback_default_deepseek_v4_flash` memory.  Use v4-pro only for ship-blocking audits via `extra_args={"model": "deepseek-v4-pro"}`.
- **Quality validation** (W14-KEYS-POOL-P3 2026-05-26): 3-way blind panel on an audit-class prompt scored v4-flash at 19/20 vs v4-pro at 20/20 on 4 axes (correctness / depth / calibration / concision).  v4-pro caught 2 additional confounders v4-flash missed (long-context latency profile, recommender-self-scoring interaction).  Tradeoff: v4-pro costs 1.5× and runs 2× slower.  Conclusion: current routing is correctly calibrated — flash for routine, pro for `audit` task class only.  Full data: `coord/reviews/v4-flash-quality-2026-05-26/SYNTHESIS.md`.
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
